"""Runs the scraper inside the server and stores each agency's result as it arrives."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import asdict

from scraper.directory import fetch_listing
from scraper.http import Fetcher
from scraper.pipeline import Result, process

from . import db, notify, settings
from .reconcile import apply_result, update_agency

log = logging.getLogger("runner")
RETRYABLE = {"rate_limited", "timeout"}


class RunManager:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self.run_id: int | None = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @staticmethod
    def recover_after_restart() -> None:
        conn = db.connect()
        with db.tx(conn):
            conn.execute("UPDATE runs SET status='stopped', error='Server restarted', finished_at=?"
                         " WHERE status IN ('running','retrying')", (db.now(),))
        conn.close()

    async def start(self, *, trigger: str, user_id: int | None, cfg: dict) -> int:
        if self.is_running():
            raise RuntimeError("A run is already in progress.")
        conn = db.connect()
        baseline = conn.execute("SELECT COUNT(*) FROM runs WHERE status='completed'").fetchone()[0] == 0
        keys = ("service", "location", "use_browser", "retry_rate_limited", "email_team", "concurrency")
        with db.tx(conn):
            cur = conn.execute("INSERT INTO runs (trigger, user_id, status, baseline, started_at, settings)"
                               " VALUES (?,?,?,?,?,?)", (trigger, user_id, "running", int(baseline), db.now(),
                                                         json.dumps({k: cfg[k] for k in keys})))
        self.run_id = cur.lastrowid
        self._task = asyncio.create_task(self._run(conn, self.run_id, cfg))
        return self.run_id

    async def stop(self) -> bool:
        if not self.is_running():
            return False
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        return True

    # ------------------------------------------------------------------
    async def _run(self, conn, run_id: int, cfg: dict) -> None:
        fetcher = Fetcher()
        browser = None
        try:
            if cfg["use_browser"]:
                try:
                    from scraper.browser import Browser
                    browser = Browser()
                    await browser.start()
                except Exception as e:  # noqa: BLE001
                    browser = None
                    self._log(conn, run_id, "warning", f"Headless browser unavailable ({e}); continuing without it")
            partners = await fetch_listing(fetcher, cfg["service"], cfg["location"] or None)
            if settings.RUN_LIMIT:
                partners = partners[: settings.RUN_LIMIT]
            agencies = self._sync_directory(conn, partners)
            with db.tx(conn):
                conn.execute("UPDATE runs SET total=? WHERE id=?", (len(partners), run_id))
            self._log(conn, run_id, "info", f"Directory lists {len(partners)} agencies")

            retry = await self._process_all(conn, run_id, partners, agencies, fetcher, browser, cfg)
            if retry and cfg["retry_rate_limited"]:
                with db.tx(conn):
                    conn.execute("UPDATE runs SET status='retrying' WHERE id=?", (run_id,))
                self._log(conn, run_id, "info", f"Retrying {len(retry)} rate-limited/timed-out agencies in "
                                                f"{settings.RETRY_DELAY_MINUTES} min")
                await asyncio.sleep(settings.RETRY_DELAY_MINUTES * 60)
                await self._process_all(conn, run_id, retry, agencies, fetcher, browser, cfg, is_retry=True)

            self._finish(conn, run_id, "completed")
            if cfg["email_team"]:
                await notify.send_digests(conn, run_id)
        except asyncio.CancelledError:
            self._finish(conn, run_id, "stopped", "Stopped by a user")
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", run_id)
            self._finish(conn, run_id, "failed", f"{type(e).__name__}: {e}"[:500])
        finally:
            await fetcher.close()
            if browser:
                await browser.close()
            conn.close()

    def _sync_directory(self, conn, partners) -> dict[str, dict]:
        at = db.now()
        with db.tx(conn):
            conn.execute("UPDATE agencies SET in_directory=0")
            for p in partners:
                conn.execute(
                    "INSERT INTO agencies (handle, name, partner_id, profile_url, created_at) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(handle) DO UPDATE SET name=excluded.name, in_directory=1",
                    (p.handle, p.name, p.partner_id, p.profile_url, at))
        return {r["handle"]: dict(r) for r in conn.execute("SELECT * FROM agencies")}

    async def _process_all(self, conn, run_id, partners, agencies, fetcher, browser, cfg, is_retry=False):
        sem = asyncio.Semaphore(int(cfg["concurrency"]))
        timeout = 300 if browser else 150
        retry = []

        async def one(p):
            async with sem:
                try:
                    res = await asyncio.wait_for(process(p, fetcher, browser), timeout)
                except asyncio.TimeoutError:
                    res = Result(partner=asdict(p), status="timeout", notes=f"exceeded {timeout}s")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - one bad site must not stop the run
                    res = Result(partner=asdict(p), status="error", notes=f"{type(e).__name__}: {e}"[:300])
            r = asdict(res)
            if r["status"] in RETRYABLE and not is_retry:
                retry.append(p)
            self._store(conn, run_id, agencies[p.handle], r, is_retry)

        await asyncio.gather(*(one(p) for p in partners))
        return retry

    def _store(self, conn, run_id: int, agency: dict, r: dict, is_retry: bool) -> None:
        at = db.now()
        baseline = conn.execute("SELECT baseline FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        with db.tx(conn):
            agency = dict(conn.execute("SELECT * FROM agencies WHERE id=?", (agency["id"],)).fetchone())
            ch = apply_result(conn, run_id=run_id, agency=agency, result=r, at=at)
            update_agency(conn, run_id=run_id, agency=agency, result=r, at=at)
            if not baseline:
                notify.create_watch_alerts(conn, run_id=run_id, agency=agency, added=ch.added, reopened=ch.reopened)
            conn.execute("INSERT OR REPLACE INTO run_agencies (run_id, agency_id, status, role_count, notes, at)"
                         " VALUES (?,?,?,?,?,?)", (run_id, agency["id"], r["status"], len(r["jobs"]), r["notes"], at))
            if not is_retry:
                conn.execute("UPDATE runs SET processed=processed+1 WHERE id=?", (run_id,))
        name = (r["partner"].get("name") or agency["name"])[:40]
        extra = f"{len(r['jobs'])} roles" if r["jobs"] else (r["notes"] or "")[:90]
        if ch.added and not baseline:
            extra += f" · {len(ch.added)} new"
        self._log(conn, run_id, r["status"], f"{name} · {extra}" + (f" · {r['careers_url']}" if r["careers_url"] else ""))

    def _finish(self, conn, run_id: int, status: str, error: str | None = None) -> None:
        counts = Counter(s for (s,) in conn.execute("SELECT status FROM run_agencies WHERE run_id=?", (run_id,)))
        q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        stats = dict(
            hiring=q("SELECT COUNT(DISTINCT agency_id) FROM roles WHERE state!='closed'"),
            roles_found=q("SELECT COUNT(*) FROM roles WHERE state!='closed'"),
            new_roles=q("SELECT COUNT(*) FROM role_events WHERE run_id=? AND type='added'", run_id),
            removed_roles=q("SELECT COUNT(*) FROM role_events WHERE run_id=? AND type='removed'", run_id),
            rate_limited=sum(v for k, v in counts.items() if k in RETRYABLE),
        )
        with db.tx(conn):
            conn.execute("UPDATE runs SET status=?, error=?, finished_at=?, status_counts=?, hiring=?, roles_found=?,"
                         " new_roles=?, removed_roles=?, rate_limited=? WHERE id=?",
                         (status, error, db.now(), json.dumps(counts), stats["hiring"], stats["roles_found"],
                          stats["new_roles"], stats["removed_roles"], stats["rate_limited"], run_id))
        self._log(conn, run_id, "info", f"Run {status}" + (f": {error}" if error else "")
                  + f" · {stats['roles_found']} open roles · {stats['new_roles']} new · {stats['removed_roles']} removed")

    @staticmethod
    def _log(conn, run_id: int, status: str, line: str) -> None:
        with db.tx(conn):
            conn.execute("INSERT INTO run_logs (run_id, at, status, line) VALUES (?,?,?,?)",
                         (run_id, db.now(), status, line))


manager = RunManager()
