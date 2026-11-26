"""Merge one agency's scrape result into the stored roles.

Rules (see README "How repeat runs are handled"):
* A role's identity is its cleaned job URL, or agency + title + location when the
  role has no URL of its own.
* Seen again -> same row: last_seen updates, user status/notes stay attached.
* New key -> new role ("added"), unless an unlisted role at the same agency has the
  same title, in which case it's a repost of that role ("reposted").
* Absent from a *successful* check -> "missing"; absent from two consecutive
  successful checks -> "removed" (closed). Failed checks never remove roles.
* A closed role that reappears is reopened, not counted as new.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Statuses where "role not listed" can be trusted to mean "role is gone".
CHECKED_OK = {"roles_found", "careers_page_no_openings"}
# Statuses where the site could not be checked at all.
FAILED = {"timeout", "error", "rate_limited", "site_unreachable", "profile_error"}

_TRACKING = re.compile(r"^(utm_|gh_src|gh_jid$|source$|ref$|fbclid|gclid|lever-source|lever-origin)", re.I)


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https"):
        return ""
    host = p.netloc.lower().removeprefix("www.")
    q = [(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)]
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", urlencode(sorted(q)), ""))


def norm_text(s: str | None) -> str:
    s = (s or "").lower().replace("sr.", "senior").replace("jr.", "junior")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def role_key(handle: str, job: dict, careers_url: str = "", website: str = "") -> str:
    url = normalize_url(job.get("url"))
    generic = {normalize_url(careers_url), normalize_url(website), ""}
    if url not in generic:
        return "u:" + url
    return f"t:{handle}:{norm_text(job.get('title'))}:{norm_text(job.get('location'))}"


# --- Classification used by the Roles filters ---
CATEGORIES = [
    ("Internship", r"\b(intern|internship|apprentice|trainee)\b"),
    ("Data & analytics", r"\b(data|analytics?|analyst|bi|insights)\b"),
    ("Engineering", r"\b(developer|engineer|engineering|programmer|devops|architect|qa|tester|technical|"
                    r"full[- ]?stack|front[- ]?end|back[- ]?end|shopify expert|technologist|cto)\b"),
    ("Design", r"\b(designer|design|ux|ui|creative director|art director|illustrator|animator|"
               r"photographer|videographer|video editor|motion)\b"),
    ("Sales", r"\b(sales|account executive|business development|bdr|sdr|closer|partnerships?)\b"),
    ("Marketing & growth", r"\b(marketing|marketer|seo|sem|ppc|paid|social|content|copywriter|writer|"
                           r"growth|email|lifecycle|retention|cro|brand|media|crm|klaviyo|community|pr)\b"),
    ("Project & account", r"\b(project|program|account manager|account lead|client|customer success|"
                          r"producer|operations|ops|coordinator|scrum|delivery|implementation)\b"),
]
_CAT_RE = [(c, re.compile(p, re.I)) for c, p in CATEGORIES]


def categorize(title: str) -> str:
    for cat, rx in _CAT_RE:
        if rx.search(title or ""):
            return cat
    return "Other"


def work_mode(location: str, title: str = "") -> str:
    text = f"{location or ''} {title or ''}"
    if re.search(r"\bhybrid\b", text, re.I):
        return "Hybrid"
    if re.search(r"\b(remote|anywhere|worldwide|work from home|wfh|distributed)\b", text, re.I):
        return "Remote"
    if re.search(r"\b(on-?site|in-office|in office|in person|in-person)\b", text, re.I):
        return "On-site"
    return "Not stated"


@dataclass
class Changes:
    added: list[dict] = field(default_factory=list)      # {"id", "title"}
    reopened: list[dict] = field(default_factory=list)
    removed: int = 0
    updated: int = 0
    open_count: int = 0


def _event(conn, role_id, agency_id, run_id, typ, at, detail=""):
    conn.execute("INSERT INTO role_events (role_id, agency_id, run_id, type, detail, at) VALUES (?,?,?,?,?,?)",
                 (role_id, agency_id, run_id, typ, detail, at))


def apply_result(conn: sqlite3.Connection, *, run_id: int, agency: dict, result: dict, at: str) -> Changes:
    """Reconcile `result["jobs"]` for one agency. Caller wraps this in a transaction."""
    ch = Changes()
    aid, handle = agency["id"], agency["handle"]
    status = result.get("status", "")
    careers_url = result.get("careers_url") or ""
    website = (result.get("partner") or {}).get("website") or agency.get("website") or ""

    existing = [dict(r) for r in conn.execute("SELECT * FROM roles WHERE agency_id=? AND manual=0", (aid,))]
    by_key = {r["key"]: r for r in existing}

    # Keys in this run (deduped, first occurrence wins).
    jobs: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for job in result.get("jobs") or []:
        if not (job.get("title") or "").strip():
            continue
        k = role_key(handle, job, careers_url, website)
        if k not in seen:
            seen.add(k)
            jobs.append((k, job))
    listed = set(seen)
    matched: set[int] = set()

    for key, job in jobs:
        title = " ".join(job["title"].split())[:200]
        loc = (job.get("location") or "").strip()[:200]
        r = by_key.get(key)
        reposted = False
        if r is None:
            # Repost: an unlisted, unmatched role at this agency with the same title.
            cands = [x for x in existing if x["id"] not in matched and x["key"] not in listed
                     and norm_text(x["title"]) == norm_text(title)]
            cands.sort(key=lambda x: {"open": 0, "missing": 1, "closed": 2}[x["state"]])
            if cands:
                r, reposted = cands[0], True
        if r is None:
            cur = conn.execute(
                "INSERT INTO roles (agency_id, key, title, location, department, url, source, confidence, category,"
                " work_mode, state, first_seen_run, first_seen_at, last_seen_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?,?,?,?)",
                (aid, key, title, loc, job.get("department", ""), job.get("url", ""), job.get("source", ""),
                 job.get("confidence", ""), categorize(title), work_mode(loc, title), run_id, at, at, at))
            _event(conn, cur.lastrowid, aid, run_id, "added", at, title)
            ch.added.append({"id": cur.lastrowid, "title": title})
            continue

        matched.add(r["id"])
        if reposted:
            _event(conn, r["id"], aid, run_id, "reposted", at, f"{r['url']} -> {job.get('url', '')}")
        elif norm_text(r["title"]) != norm_text(title) or norm_text(r["location"]) != norm_text(loc):
            _event(conn, r["id"], aid, run_id, "updated", at, f"{r['title']} | {r['location']} -> {title} | {loc}")
            ch.updated += 1
        if r["state"] == "closed":
            _event(conn, r["id"], aid, run_id, "reopened", at, title)
            ch.reopened.append({"id": r["id"], "title": title})
        conn.execute(
            "UPDATE roles SET key=?, title=?, location=?, department=?, url=?, source=?, confidence=?, category=?,"
            " work_mode=?, state='open', missing_count=0, closed_at=NULL, last_seen_at=?, updated_at=? WHERE id=?",
            (key, title, loc, job.get("department", ""), job.get("url", ""), job.get("source", ""),
             job.get("confidence", ""), categorize(title), work_mode(loc, title), at, at, r["id"]))

    if status in CHECKED_OK:
        for r in existing:
            if r["id"] in matched or r["state"] == "closed":
                continue
            if r["state"] == "open":
                conn.execute("UPDATE roles SET state='missing', missing_count=1, updated_at=? WHERE id=?", (at, r["id"]))
                _event(conn, r["id"], aid, run_id, "missing", at, r["title"])
            else:  # second consecutive miss
                conn.execute("UPDATE roles SET state='closed', missing_count=missing_count+1, closed_at=?, updated_at=?"
                             " WHERE id=?", (at, at, r["id"]))
                _event(conn, r["id"], aid, run_id, "removed", at, r["title"])
                ch.removed += 1

    ch.open_count = conn.execute("SELECT COUNT(*) FROM roles WHERE agency_id=? AND state!='closed'", (aid,)).fetchone()[0]
    return ch


def update_agency(conn: sqlite3.Connection, *, run_id: int, agency: dict, result: dict, at: str) -> None:
    """Store the latest check result on the agency row (keeps old data when the check failed)."""
    p = result.get("partner") or {}
    status = result.get("status", "")
    failed = status in FAILED
    profile = {k: p.get(k) for k in ("name", "partner_id", "profile_url", "tier", "location", "team_size",
                                     "partner_since", "website", "linkedin") if p.get(k)}
    sets = dict(profile, status=status, notes=result.get("notes", ""), last_checked_at=at, last_run_id=run_id,
                used_browser=int(bool(result.get("used_browser"))))
    if not failed:
        sets.update(final_url=result.get("final_url", ""), careers_url=result.get("careers_url", ""),
                    discovery_method=result.get("discovery_method", ""), ats=result.get("ats", ""),
                    ats_board=result.get("ats_board", ""), careers_email=result.get("careers_email", ""),
                    careers_hash=result.get("careers_hash", ""), last_success_at=at)
        # A reviewed careers page that changed goes back into the review queue,
        # and roles added by hand are flagged so someone re-checks them.
        new_hash = result.get("careers_hash", "")
        if agency.get("review_state") and agency.get("review_hash") and new_hash and new_hash != agency["review_hash"]:
            sets.update(review_state=None, review_hash=None, reviewed_by=None, reviewed_at=None)
            conn.execute("UPDATE roles SET needs_recheck=1 WHERE agency_id=? AND manual=1 AND state!='closed'",
                         (agency["id"],))
    cols = ", ".join(f"{k}=?" for k in sets)
    conn.execute(f"UPDATE agencies SET {cols} WHERE id=?", (*sets.values(), agency["id"]))
