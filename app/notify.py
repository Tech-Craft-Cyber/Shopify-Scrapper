"""Watched-agency alerts (in-app) and optional email digests via SMTP."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from . import db, settings

log = logging.getLogger("notify")


def create_watch_alerts(conn, *, run_id: int, agency: dict, added: list[dict], reopened: list[dict]) -> None:
    """Called inside the reconcile transaction for one agency."""
    titles = [r["title"] for r in added + reopened]
    if not titles:
        return
    shown = ", ".join(titles[:4]) + (f" and {len(titles) - 4} more" if len(titles) > 4 else "")
    msg = f"{agency['name']} posted {len(titles)} new role{'s' if len(titles) > 1 else ''}: {shown}"
    for (uid,) in conn.execute("SELECT user_id FROM watches WHERE agency_id=?", (agency["id"],)).fetchall():
        conn.execute("INSERT INTO alerts (user_id, agency_id, run_id, message, created_at) VALUES (?,?,?,?,?)",
                     (uid, agency["id"], run_id, msg, db.now()))


def email_enabled() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as s:
        if settings.SMTP_STARTTLS:
            s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        s.send_message(msg)


async def send_digests(conn, run_id: int) -> None:
    """After a run: email every user the new roles plus their watched-agency alerts."""
    if not email_enabled():
        return
    new = db.rows(conn.execute(
        "SELECT r.title, r.location, r.url, a.name AS agency FROM role_events e JOIN roles r ON r.id=e.role_id"
        " JOIN agencies a ON a.id=r.agency_id WHERE e.run_id=? AND e.type IN ('added','reopened') ORDER BY a.name",
        (run_id,)))
    link = settings.PUBLIC_URL.rstrip("/")
    for u in db.rows(conn.execute("SELECT id, email, name FROM users")):
        alerts = db.rows(conn.execute("SELECT id, message FROM alerts WHERE user_id=? AND emailed=0 ORDER BY id",
                                      (u["id"],)))
        if not new and not alerts:
            continue
        lines = [f"Hi {u['name']},", ""]
        if alerts:
            lines += ["Agencies you watch:"] + [f"  • {a['message']}" for a in alerts] + [""]
        if new:
            lines += [f"{len(new)} new role{'s' if len(new) != 1 else ''} in this scrape:"]
            lines += [f"  • {r['title']} — {r['agency']}" + (f" ({r['location']})" if r["location"] else "")
                      + (f"\n    {r['url']}" if r["url"] else "") for r in new[:50]]
            if len(new) > 50:
                lines.append(f"  …and {len(new) - 50} more.")
        if link:
            lines += ["", f"Open the board: {link}"]
        try:
            await asyncio.to_thread(_send, u["email"], f"Agency Roles: {len(new)} new roles", "\n".join(lines))
            if alerts:
                with db.tx(conn):
                    conn.executemany("UPDATE alerts SET emailed=1 WHERE id=?", [(a["id"],) for a in alerts])
        except Exception:  # noqa: BLE001
            log.exception("email to %s failed", u["email"])
