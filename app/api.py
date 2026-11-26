"""JSON API used by the React app."""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import auth, db, notify, scheduler, settings
from .auth import current_user, get_conn, require_admin
from .reconcile import categorize, work_mode
from .runner import manager

router = APIRouter(prefix="/api")

VERIFIED_SOURCES = {"greenhouse", "lever", "ashby", "workable", "recruitee", "breezy", "smartrecruiters",
                    "bamboohr", "personio", "jsonld"}
SOURCE_LABEL = {"jsonld": "JSON-LD", "smartrecruiters": "SmartRecruiters", "bamboohr": "BambooHR",
                "jazzhr": "JazzHR", "html-link": "Careers page", "html-section": "Careers page",
                "html-heading": "Careers page", "manual": "Added by hand"}
STATUS_LABEL = {
    "roles_found": "Hiring", "careers_page_no_openings": "Careers page, no openings",
    "careers_page_roles_unclear": "Needs review", "no_careers_page": "No careers page",
    "site_unreachable": "Site unreachable", "no_website": "No company website",
    "non_company_site": "No company website", "rate_limited": "Rate limited / timed out",
    "timeout": "Rate limited / timed out", "error": "Errors", "profile_error": "Errors",
}


def initials(name: str) -> str:
    parts = [p for p in (name or "?").split() if p]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def source_info(r: dict) -> dict:
    src = (r.get("source") or "").lower()
    if r.get("manual"):
        return {"kind": "manual", "label": "Added by hand"}
    if src in VERIFIED_SOURCES or r.get("confidence") == "high":
        return {"kind": "verified", "label": SOURCE_LABEL.get(src, src.title())}
    if r.get("confidence") == "low":
        return {"kind": "check", "label": "Check"}
    return {"kind": "parsed", "label": SOURCE_LABEL.get(src, src.title() or "Careers page")}


def new_marker(conn) -> tuple[int | None, set[int]]:
    """Roles first seen in the latest completed run (or the one in progress) are 'new'."""
    latest = conn.execute("SELECT MAX(id) FROM runs WHERE status='completed'").fetchone()[0]
    baseline = {r for (r,) in conn.execute("SELECT id FROM runs WHERE baseline=1")}
    return latest, baseline


def is_new(role: dict, latest: int | None, baseline: set[int]) -> bool:
    fr = role.get("first_seen_run")
    return bool(latest and fr and fr >= latest and fr not in baseline and not role.get("manual"))


def agency_display_status(a: dict, open_roles: int) -> str:
    if open_roles:
        return "hiring"
    if a.get("review_state") == "ignored":
        return "other"
    if a.get("review_state") == "no_openings" or a.get("status") == "careers_page_no_openings":
        return "no_openings"
    if a.get("status") == "careers_page_roles_unclear":
        return "needs_review"
    if a.get("status") == "no_careers_page":
        return "no_careers"
    return "other"


def review_reason(a: dict) -> str:
    notes = (a.get("notes") or "").lower()
    if "fetch failed" in notes:
        return "Page failed to load"
    if a.get("ats"):
        return "Job board unreadable"
    if a.get("used_browser"):
        return "Page needs a browser"
    return "No role titles found"


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, conn=Depends(get_conn)):
    ip = request.client.host if request.client else "?"
    if auth.throttle.blocked(ip):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    u = db.one(conn.execute("SELECT * FROM users WHERE email=?", (body.email.strip(),)))
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        auth.throttle.fail(ip)
        raise HTTPException(401, "Wrong email or password.")
    token = auth.create_session(conn, u["id"])
    response.set_cookie(auth.COOKIE, token, max_age=settings.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=settings.COOKIE_SECURE)
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"])}


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    token = request.cookies.get(auth.COOKIE)
    if token:
        with db.tx(conn):
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return dict(user, is_admin=bool(user["is_admin"]), initials=initials(user["name"]))


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=10)


@router.post("/me/password")
def change_password(body: PasswordIn, user=Depends(current_user), conn=Depends(get_conn)):
    row = db.one(conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)))
    if not auth.verify_password(body.current, row["password_hash"]):
        raise HTTPException(400, "Current password is wrong.")
    with db.tx(conn):
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(body.new), user["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- summary
@router.get("/summary")
def summary(user=Depends(current_user), conn=Depends(get_conn)):
    latest, baseline = new_marker(conn)
    roles = db.rows(conn.execute("SELECT first_seen_run, manual FROM roles WHERE state!='closed'"))
    last = db.one(conn.execute("SELECT id, status, finished_at, new_roles FROM runs WHERE status='completed'"
                               " ORDER BY id DESC LIMIT 1"))
    cur = db.one(conn.execute("SELECT id, status, total, processed, started_at FROM runs"
                              " WHERE status IN ('running','retrying') ORDER BY id DESC LIMIT 1"))
    needs_review = conn.execute("SELECT COUNT(*) FROM agencies a WHERE a.status='careers_page_roles_unclear'"
                                " AND a.review_state IS NULL AND a.in_directory=1 AND NOT EXISTS"
                                " (SELECT 1 FROM roles r WHERE r.agency_id=a.id AND r.state!='closed')").fetchone()[0]
    unread = conn.execute("SELECT COUNT(*) FROM alerts WHERE user_id=? AND read_at IS NULL", (user["id"],)).fetchone()[0]
    return {"open_roles": len(roles), "new_roles": sum(is_new(r, latest, baseline) for r in roles),
            "needs_review": needs_review, "unread_alerts": unread, "last_run": last, "current_run": cur}


# ---------------------------------------------------------------- roles
def _team_activity(conn, me_id: int) -> tuple[dict, dict]:
    mine, team = {}, defaultdict(list)
    for r in conn.execute("SELECT ur.role_id, ur.status, ur.note, ur.updated_at, u.id AS uid, u.name FROM user_roles ur"
                          " JOIN users u ON u.id=ur.user_id"):
        if r["uid"] == me_id:
            mine[r["role_id"]] = {"status": r["status"], "note": r["note"] or ""}
        elif r["status"] in ("saved", "applied"):
            team[r["role_id"]].append({"user_id": r["uid"], "name": r["name"], "initials": initials(r["name"]),
                                       "status": r["status"], "at": r["updated_at"]})
    return mine, team


ROLE_SQL = """SELECT r.*, a.name AS agency_name, a.handle AS agency_handle, a.tier AS agency_tier,
    a.location AS agency_location, a.team_size AS agency_team_size, a.website AS agency_website,
    a.careers_url AS agency_careers_url,
    u.name AS added_by_name
    FROM roles r JOIN agencies a ON a.id=r.agency_id LEFT JOIN users u ON u.id=r.added_by"""


def _role_out(r: dict, latest, baseline, mine, team) -> dict:
    return {
        "id": r["id"], "title": r["title"], "location": r["location"] or "", "department": r["department"] or "",
        # Roles found as headings have no page of their own: send people to the careers page.
        "url": r["url"] or r.get("agency_careers_url") or "",
        "url_kind": "job" if r["url"] else "careers",
        "category": r["category"] or categorize(r["title"]),
        "work_mode": r["work_mode"] or work_mode(r["location"] or "", r["title"]),
        "state": r["state"], "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"],
        "is_new": is_new(r, latest, baseline), "manual": bool(r["manual"]), "needs_recheck": bool(r["needs_recheck"]),
        "added_by": r.get("added_by_name"), "source": source_info(r),
        "agency": {"id": r["agency_id"], "name": r["agency_name"], "handle": r["agency_handle"],
                   "tier": r["agency_tier"] or "", "location": r["agency_location"] or "",
                   "team_size": r["agency_team_size"] or "", "website": r["agency_website"] or ""},
        "my": mine.get(r["id"], {"status": None, "note": ""}),
        "team": team.get(r["id"], []),
    }


@router.get("/roles")
def list_roles(user=Depends(current_user), conn=Depends(get_conn)):
    """All open roles. The client filters/sorts (a few thousand rows at most)."""
    latest, baseline = new_marker(conn)
    mine, team = _team_activity(conn, user["id"])
    rows = db.rows(conn.execute(ROLE_SQL + " WHERE r.state!='closed' ORDER BY r.first_seen_at DESC, r.id DESC"))
    return [_role_out(r, latest, baseline, mine, team) for r in rows]


@router.get("/roles/{role_id}")
def role_detail(role_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    latest, baseline = new_marker(conn)
    mine, team = _team_activity(conn, user["id"])
    r = db.one(conn.execute(ROLE_SQL + " WHERE r.id=?", (role_id,)))
    if not r:
        raise HTTPException(404, "Role not found")
    out = _role_out(r, latest, baseline, mine, team)
    a = db.one(conn.execute("SELECT * FROM agencies WHERE id=?", (r["agency_id"],)))
    out["agency"].update(careers_url=a["careers_url"] or "", linkedin=a["linkedin"] or "",
                         profile_url=a["profile_url"] or "", partner_since=a["partner_since"] or "",
                         watching=bool(conn.execute("SELECT 1 FROM watches WHERE user_id=? AND agency_id=?",
                                                    (user["id"], a["id"])).fetchone()))
    out["more_roles"] = db.rows(conn.execute(
        "SELECT id, title, location FROM roles WHERE agency_id=? AND id!=? AND state!='closed' ORDER BY title",
        (a["id"], role_id)))
    # Team activity on this role and at this agency.
    out["activity"] = db.rows(conn.execute(
        "SELECT u.name, ur.status, ur.updated_at AS at, r.title, r.id AS role_id FROM user_roles ur"
        " JOIN users u ON u.id=ur.user_id JOIN roles r ON r.id=ur.role_id"
        " WHERE r.agency_id=? AND ur.user_id!=? AND ur.status IN ('saved','applied') ORDER BY ur.updated_at DESC LIMIT 10",
        (a["id"], user["id"])))
    for x in out["activity"]:
        x["initials"] = initials(x["name"])
    out["history"] = db.rows(conn.execute("SELECT type, detail, at FROM role_events WHERE role_id=? ORDER BY id DESC"
                                          " LIMIT 10", (role_id,)))
    return out


class RoleStatusIn(BaseModel):
    status: str | None = None     # saved | applied | not_interested | None
    note: str | None = None


@router.put("/roles/{role_id}/me")
def set_role_status(role_id: int, body: RoleStatusIn, user=Depends(current_user), conn=Depends(get_conn)):
    if body.status not in (None, "saved", "applied", "not_interested"):
        raise HTTPException(400, "Unknown status")
    if not conn.execute("SELECT 1 FROM roles WHERE id=?", (role_id,)).fetchone():
        raise HTTPException(404, "Role not found")
    cur = db.one(conn.execute("SELECT status, note FROM user_roles WHERE user_id=? AND role_id=?", (user["id"], role_id)))
    note = body.note if body.note is not None else (cur or {}).get("note", "")
    with db.tx(conn):
        conn.execute("INSERT INTO user_roles (user_id, role_id, status, note, updated_at) VALUES (?,?,?,?,?)"
                     " ON CONFLICT(user_id, role_id) DO UPDATE SET status=excluded.status, note=excluded.note,"
                     " updated_at=excluded.updated_at", (user["id"], role_id, body.status, (note or "")[:4000], db.now()))
    return {"status": body.status, "note": note}


@router.get("/roles.csv")
def export_roles(user=Depends(current_user), conn=Depends(get_conn)):
    rows = list_roles(user, conn)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "agency", "tier", "location", "work_mode", "category", "source", "new", "my_status", "url"])
    for r in rows:
        w.writerow([r["title"], r["agency"]["name"], r["agency"]["tier"], r["location"], r["work_mode"], r["category"],
                    r["source"]["label"], "yes" if r["is_new"] else "", r["my"]["status"] or "", r["url"]])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=open-roles.csv"})


# ---------------------------------------------------------------- agencies
@router.get("/agencies")
def list_agencies(user=Depends(current_user), conn=Depends(get_conn)):
    latest, baseline = new_marker(conn)
    open_by, new_by = defaultdict(int), defaultdict(int)
    for r in db.rows(conn.execute("SELECT agency_id, first_seen_run, manual FROM roles WHERE state!='closed'")):
        open_by[r["agency_id"]] += 1
        new_by[r["agency_id"]] += is_new(r, latest, baseline)
    watched = {a for (a,) in conn.execute("SELECT agency_id FROM watches WHERE user_id=?", (user["id"],))}
    team = defaultdict(set)
    for r in conn.execute("SELECT r.agency_id, u.name FROM user_roles ur JOIN roles r ON r.id=ur.role_id"
                          " JOIN users u ON u.id=ur.user_id WHERE ur.status IN ('saved','applied')"):
        team[r["agency_id"]].add(r["name"])
    out = []
    for a in db.rows(conn.execute("SELECT * FROM agencies WHERE in_directory=1 ORDER BY name COLLATE NOCASE")):
        n = open_by[a["id"]]
        out.append({
            "id": a["id"], "handle": a["handle"], "name": a["name"], "tier": a["tier"] or "",
            "location": a["location"] or "", "team_size": a["team_size"] or "", "website": a["website"] or "",
            "careers_url": a["careers_url"] or "", "careers_email": a["careers_email"] or "",
            "ats": a["ats"] or "", "ats_board": a["ats_board"] or "", "raw_status": a["status"] or "",
            "status": agency_display_status(a, n), "open_roles": n, "new_roles": new_by[a["id"]],
            "watching": a["id"] in watched, "team": [{"name": t, "initials": initials(t)} for t in sorted(team[a["id"]])],
            "last_checked_at": a["last_checked_at"], "notes": a["notes"] or "",
            "review_reason": review_reason(a), "review_state": a["review_state"],
            "linkedin": a["linkedin"] or "", "profile_url": a["profile_url"] or "",
        })
    return out


@router.get("/agencies/{agency_id}")
def agency_detail(agency_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    a = db.one(conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)))
    if not a:
        raise HTTPException(404, "Agency not found")
    latest, baseline = new_marker(conn)
    mine, team = _team_activity(conn, user["id"])
    roles = [_role_out(r, latest, baseline, mine, team)
             for r in db.rows(conn.execute(ROLE_SQL + " WHERE r.agency_id=? AND r.state!='closed' ORDER BY r.title",
                                           (agency_id,)))]
    history = db.rows(conn.execute("SELECT e.type, e.detail, e.at FROM role_events e WHERE e.agency_id=?"
                                   " AND e.type IN ('added','removed','reopened','reposted') ORDER BY e.id DESC LIMIT 30",
                                   (agency_id,)))
    return {"agency": a, "roles": roles, "history": history,
            "watching": bool(conn.execute("SELECT 1 FROM watches WHERE user_id=? AND agency_id=?",
                                          (user["id"], agency_id)).fetchone())}


@router.put("/agencies/{agency_id}/watch")
def watch(agency_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    with db.tx(conn):
        conn.execute("INSERT OR IGNORE INTO watches (user_id, agency_id, created_at) VALUES (?,?,?)",
                     (user["id"], agency_id, db.now()))
    return {"watching": True}


@router.delete("/agencies/{agency_id}/watch")
def unwatch(agency_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    with db.tx(conn):
        conn.execute("DELETE FROM watches WHERE user_id=? AND agency_id=?", (user["id"], agency_id))
    return {"watching": False}


class ReviewIn(BaseModel):
    action: str   # no_openings | ignored | reopen


@router.post("/agencies/{agency_id}/review")
def review(agency_id: int, body: ReviewIn, user=Depends(current_user), conn=Depends(get_conn)):
    a = db.one(conn.execute("SELECT careers_hash FROM agencies WHERE id=?", (agency_id,)))
    if not a:
        raise HTTPException(404, "Agency not found")
    if body.action not in ("no_openings", "ignored", "reopen"):
        raise HTTPException(400, "Unknown action")
    with db.tx(conn):
        if body.action == "reopen":
            conn.execute("UPDATE agencies SET review_state=NULL, review_hash=NULL, reviewed_by=NULL, reviewed_at=NULL"
                         " WHERE id=?", (agency_id,))
        else:
            conn.execute("UPDATE agencies SET review_state=?, review_hash=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                         (body.action, a["careers_hash"], user["id"], db.now(), agency_id))
    return {"ok": True}


class ManualRoleIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    location: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=1000)


@router.post("/agencies/{agency_id}/roles")
def add_manual_role(agency_id: int, body: ManualRoleIn, user=Depends(current_user), conn=Depends(get_conn)):
    a = db.one(conn.execute("SELECT id, handle, careers_url, careers_hash FROM agencies WHERE id=?", (agency_id,)))
    if not a:
        raise HTTPException(404, "Agency not found")
    if body.url and not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "Apply URL must start with http:// or https://")
    at = db.now()
    key = f"m:{a['handle']}:{at}:{body.title.lower()}"
    with db.tx(conn):
        cur = conn.execute(
            "INSERT INTO roles (agency_id, key, title, location, url, source, confidence, category, work_mode, state,"
            " first_seen_at, last_seen_at, updated_at, manual, added_by) VALUES (?,?,?,?,?,'manual','medium',?,?,'open',?,?,?,1,?)",
            (agency_id, key, body.title.strip(), body.location.strip(), body.url.strip() or a["careers_url"],
             categorize(body.title), work_mode(body.location, body.title), at, at, at, user["id"]))
        conn.execute("INSERT INTO role_events (role_id, agency_id, type, detail, at) VALUES (?,?,'added',?,?)",
                     (cur.lastrowid, agency_id, f"added by hand: {body.title}", at))
        conn.execute("UPDATE agencies SET review_state='roles_added', review_hash=?, reviewed_by=?, reviewed_at=?"
                     " WHERE id=?", (a["careers_hash"], user["id"], at, agency_id))
    return {"id": cur.lastrowid}


@router.delete("/roles/{role_id}")
def close_manual_role(role_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    r = db.one(conn.execute("SELECT manual, agency_id, title FROM roles WHERE id=?", (role_id,)))
    if not r or not r["manual"]:
        raise HTTPException(400, "Only roles added by hand can be closed manually.")
    with db.tx(conn):
        conn.execute("UPDATE roles SET state='closed', closed_at=?, needs_recheck=0 WHERE id=?", (db.now(), role_id))
        conn.execute("INSERT INTO role_events (role_id, agency_id, type, detail, at) VALUES (?,?,'removed',?,?)",
                     (role_id, r["agency_id"], f"closed by {user['name']}", db.now()))
    return {"ok": True}


# ---------------------------------------------------------------- runs & schedule
@router.get("/runs")
def runs(user=Depends(current_user), conn=Depends(get_conn)):
    history = db.rows(conn.execute(
        "SELECT r.id, r.trigger, r.status, r.baseline, r.started_at, r.finished_at, r.total, r.processed, r.hiring,"
        " r.roles_found, r.new_roles, r.removed_roles, r.rate_limited, r.error, u.name AS user_name"
        " FROM runs r LEFT JOIN users u ON u.id=r.user_id ORDER BY r.id DESC LIMIT 25"))
    current = next((h for h in history if h["status"] in ("running", "retrying")), None)
    if current:
        q = lambda sql: conn.execute(sql, (current["id"],)).fetchone()[0]  # noqa: E731
        current.update(
            live_hiring=q("SELECT COUNT(*) FROM run_agencies WHERE run_id=? AND role_count>0"),
            live_roles=q("SELECT COALESCE(SUM(role_count),0) FROM run_agencies WHERE run_id=?"),
            live_new=q("SELECT COUNT(*) FROM role_events WHERE run_id=? AND type='added'"),
            live_rate_limited=q("SELECT COUNT(*) FROM run_agencies WHERE run_id=? AND status IN ('rate_limited','timeout')"),
        )
    completed = [h for h in history if h["status"] == "completed"]
    last = completed[0] if completed else None
    prev = completed[1] if len(completed) > 1 else None
    breakdown = []
    if last:
        sc = json.loads(db.one(conn.execute("SELECT status_counts FROM runs WHERE id=?", (last["id"],)))["status_counts"]
                        or "{}")
        agg = defaultdict(int)
        for k, v in sc.items():
            agg[STATUS_LABEL.get(k, k)] += v
        breakdown = sorted(({"label": k, "count": v} for k, v in agg.items()), key=lambda x: -x["count"])
    open_roles = db.rows(conn.execute("SELECT source, confidence, manual FROM roles WHERE state!='closed'"))
    verified = sum(source_info(r)["kind"] == "verified" for r in open_roles)
    return {
        "current": current,
        "history": history,
        "tiles": {
            "open_roles": len(open_roles),
            "open_roles_delta": (last["roles_found"] - prev["roles_found"]) if last and prev else None,
            "agencies_hiring": conn.execute("SELECT COUNT(DISTINCT agency_id) FROM roles WHERE state!='closed'").fetchone()[0],
            "agencies_total": conn.execute("SELECT COUNT(*) FROM agencies WHERE in_directory=1").fetchone()[0],
            "new_last_run": last["new_roles"] if last and not last["baseline"] else None,
            "removed_last_run": last["removed_roles"] if last else None,
            "verified_pct": round(100 * verified / len(open_roles)) if open_roles else None,
        },
        "breakdown": breakdown,
        "new_per_run": [{"id": h["id"], "started_at": h["started_at"], "new_roles": h["new_roles"],
                         "baseline": bool(h["baseline"])} for h in reversed(completed[:14])],
    }


@router.get("/runs/{run_id}/log")
def run_log(run_id: int, after: int = 0, user=Depends(current_user), conn=Depends(get_conn)):
    return db.rows(conn.execute("SELECT id, at, status, line FROM run_logs WHERE run_id=? AND id>? ORDER BY id LIMIT 500",
                                (run_id, after)))


@router.post("/runs")
async def run_now(user=Depends(require_admin), conn=Depends(get_conn)):
    if manager.is_running():
        raise HTTPException(409, "A run is already in progress.")
    run_id = await manager.start(trigger="manual", user_id=user["id"], cfg=scheduler.load(conn))
    return {"id": run_id}


@router.post("/runs/stop")
async def stop_run(user=Depends(require_admin)):
    return {"stopped": await manager.stop()}


def _schedule_out(s: dict) -> dict:
    now = datetime.now(timezone.utc)
    try:
        nxt = [t.isoformat() for t in scheduler.next_runs(s, now, 3)] if s["enabled"] else []
    except Exception:  # noqa: BLE001
        nxt = []
    return dict(s, next_runs=nxt, description=scheduler.describe(s), email_available=notify.email_enabled())


@router.get("/schedule")
def get_schedule(user=Depends(current_user), conn=Depends(get_conn)):
    return _schedule_out(scheduler.load(conn))


class ScheduleIn(BaseModel):
    enabled: bool
    mode: str
    interval_hours: int = 6
    time: str
    timezone: str
    days: str
    cron: str = "0 6 * * *"
    service: str = "store_building"
    location: str = "US"
    use_browser: bool = True
    retry_rate_limited: bool = True
    email_team: bool = False
    skip_if_running: bool = True
    concurrency: int = 8


@router.put("/schedule")
def put_schedule(body: ScheduleIn, user=Depends(require_admin), conn=Depends(get_conn)):
    try:
        s = scheduler.validate(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    cols = [k for k in ScheduleIn.model_fields]
    with db.tx(conn):
        conn.execute(f"UPDATE schedule SET {', '.join(c + '=?' for c in cols)}, last_fired_at=? WHERE id=1",
                     (*[s[c] for c in cols], db.now()))
    return _schedule_out(scheduler.load(conn))


@router.post("/schedule/preview")
def preview_schedule(body: ScheduleIn, user=Depends(current_user)):
    try:
        s = scheduler.validate(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"next_runs": [t.isoformat() for t in scheduler.next_runs(s, datetime.now(timezone.utc), 3)],
            "description": scheduler.describe(s)}


# ---------------------------------------------------------------- alerts
@router.get("/alerts")
def alerts(user=Depends(current_user), conn=Depends(get_conn)):
    return db.rows(conn.execute("SELECT id, agency_id, message, created_at, read_at FROM alerts WHERE user_id=?"
                                " ORDER BY id DESC LIMIT 40", (user["id"],)))


@router.post("/alerts/read")
def alerts_read(user=Depends(current_user), conn=Depends(get_conn)):
    with db.tx(conn):
        conn.execute("UPDATE alerts SET read_at=? WHERE user_id=? AND read_at IS NULL", (db.now(), user["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- team (admin)
@router.get("/users")
def users(user=Depends(require_admin), conn=Depends(get_conn)):
    return db.rows(conn.execute("SELECT id, email, name, is_admin, created_at FROM users ORDER BY name"))


class UserIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10)
    is_admin: bool = False


@router.post("/users")
def add_user(body: UserIn, user=Depends(require_admin), conn=Depends(get_conn)):
    if "@" not in body.email:
        raise HTTPException(400, "That doesn't look like an email address.")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (body.email.strip(),)).fetchone():
        raise HTTPException(400, "A user with that email already exists.")
    return {"id": auth.create_user(conn, body.email, body.name, body.password, body.is_admin)}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user=Depends(require_admin), conn=Depends(get_conn)):
    if user_id == user["id"]:
        raise HTTPException(400, "You can't remove yourself.")
    with db.tx(conn):
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"ok": True}
