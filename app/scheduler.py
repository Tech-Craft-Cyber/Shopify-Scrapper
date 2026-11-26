"""Schedule maths + the background loop that starts scheduled runs."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from . import db

log = logging.getLogger("scheduler")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MODES = {"interval", "daily", "cron"}


def validate(s: dict) -> dict:
    """Normalise and validate a schedule dict. Raises ValueError with a readable message."""
    out = dict(s)
    if out.get("mode") not in MODES:
        raise ValueError("Repeat must be one of: every few hours, daily, cron.")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", out.get("time", "")):
        raise ValueError("Time must look like 06:00.")
    try:
        ZoneInfo(out.get("timezone", ""))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone: {out.get('timezone')!r}.")
    days = [d for d in str(out.get("days", "")).lower().split(",") if d]
    if out["mode"] == "daily" and (not days or any(d not in DAYS for d in days)):
        raise ValueError("Pick at least one day.")
    out["days"] = ",".join(d for d in DAYS if d in days) or ",".join(DAYS)
    hours = int(out.get("interval_hours") or 0)
    if out["mode"] == "interval" and not 1 <= hours <= 24:
        raise ValueError("Every few hours must be between 1 and 24.")
    out["interval_hours"] = hours or 6
    if out["mode"] == "cron" and not croniter.is_valid(out.get("cron", "")):
        raise ValueError("That cron expression isn't valid (e.g. 0 6 * * 1-5).")
    conc = int(out.get("concurrency") or 8)
    if not 1 <= conc <= 16:
        raise ValueError("Concurrency must be between 1 and 16.")
    out["concurrency"] = conc
    if not re.fullmatch(r"[a-z0-9_]+", out.get("service", "")):
        raise ValueError("Directory service should look like store_building.")
    if not re.fullmatch(r"[A-Z]{2}|", out.get("location", "")):
        raise ValueError("Location should be a 2-letter country code (e.g. US) or empty for all.")
    for k in ("enabled", "use_browser", "retry_rate_limited", "email_team", "skip_if_running"):
        out[k] = int(bool(out.get(k)))
    return out


def next_runs(s: dict, after: datetime, n: int = 3) -> list[datetime]:
    """The next `n` fire times strictly after `after` (aware datetimes, UTC)."""
    tz = ZoneInfo(s["timezone"])
    local = after.astimezone(tz)
    hh, mm = map(int, s["time"].split(":"))
    out: list[datetime] = []
    if s["mode"] == "cron":
        it = croniter(s["cron"], local)
        while len(out) < n:
            out.append(it.get_next(datetime).astimezone(timezone.utc))
        return out
    if s["mode"] == "interval":
        step = timedelta(hours=int(s["interval_hours"]))
        t = local.replace(hour=hh, minute=mm, second=0, microsecond=0) - timedelta(days=1)
        while len(out) < n:
            t += step
            if t > local:
                out.append(t.astimezone(timezone.utc))
        return out
    days = set(s["days"].split(","))
    d = local.date()
    for _ in range(366):
        t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        if t > local and DAYS[t.weekday()] in days:
            out.append(t.astimezone(timezone.utc))
            if len(out) == n:
                break
        d += timedelta(days=1)
    return out


def describe(s: dict) -> str:
    if s["mode"] == "cron":
        return f"Cron {s['cron']} ({s['timezone']})"
    if s["mode"] == "interval":
        return f"Every {s['interval_hours']} h from {s['time']} ({s['timezone']})"
    days = s["days"].split(",")
    when = "every day" if len(days) == 7 else ("weekdays" if days == DAYS[:5] else ", ".join(d.title() for d in days))
    return f"{when.capitalize()} at {s['time']} ({s['timezone']})"


def load(conn) -> dict:
    return db.one(conn.execute("SELECT * FROM schedule WHERE id=1"))


async def loop(manager, poll_seconds: int = 30) -> None:
    """Fire runs when due. Missed runs while the server was down are skipped, not replayed."""
    started = datetime.now(timezone.utc)
    conn = db.connect()
    try:
        while True:
            try:
                s = load(conn)
                if s["enabled"]:
                    last = datetime.fromisoformat(s["last_fired_at"]) if s["last_fired_at"] else started
                    base = max(last, started)
                    due = next_runs(s, base, 1)[0]
                    now = datetime.now(timezone.utc)
                    if now >= due:
                        with db.tx(conn):
                            conn.execute("UPDATE schedule SET last_fired_at=? WHERE id=1", (now.isoformat(timespec="seconds"),))
                        if manager.is_running():
                            # Runs never overlap; the setting only decides how loudly we note it.
                            (log.info if s["skip_if_running"] else log.warning)(
                                "Scheduled run skipped: previous run still going")
                        else:
                            await manager.start(trigger="schedule", user_id=None, cfg=s)
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("scheduler tick failed")
            await asyncio.sleep(poll_seconds)
    finally:
        conn.close()
