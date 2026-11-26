"""Applicant-tracking-system (ATS) detection and public job-board feeds.

Agencies frequently host their openings on an ATS rather than on their own
site. When a careers page links to / embeds one, its public JSON feed is the
most reliable source of roles (titles, locations, apply URLs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from lxml import html as LH

from .http import Fetcher


@dataclass
class Job:
    title: str
    location: str = ""
    department: str = ""
    url: str = ""
    source: str = ""        # greenhouse | lever | ... | jsonld | html
    confidence: str = ""    # high | medium | low


TOKEN = r"([A-Za-z0-9][A-Za-z0-9_.-]*)"
SUB = r"([A-Za-z0-9][A-Za-z0-9-]*)"
ATS_PATTERNS: list[tuple[str, re.Pattern]] = [(n, re.compile(p, re.I)) for n, p in [
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=" + TOKEN),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/" + TOKEN),
    ("greenhouse", r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/" + TOKEN),
    ("lever", r"api\.(?:eu\.)?lever\.co/v0/postings/" + TOKEN),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/" + TOKEN),
    ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/" + TOKEN),
    ("ashby", r"jobs\.ashbyhq\.com/" + TOKEN),
    ("workable", r"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?" + TOKEN),
    ("workable", SUB + r"\.workable\.com"),
    ("recruitee", SUB + r"\.recruitee\.com"),
    ("breezy", SUB + r"\.breezy\.hr"),
    ("smartrecruiters", r"api\.smartrecruiters\.com/v1/companies/" + TOKEN),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/" + TOKEN),
    ("bamboohr", SUB + r"\.bamboohr\.com"),
    ("jazzhr", SUB + r"\.applytojob\.com"),
    ("personio", SUB + r"\.jobs\.personio\.(?:de|com)"),
    ("teamtailor", SUB + r"\.teamtailor\.com"),
    ("rippling", r"ats\.rippling\.com/" + TOKEN),
    ("gusto", r"jobs\.gusto\.com/(?:boards|postings)/" + TOKEN),
    ("wellfound", r"(?:wellfound\.com|angel\.co)/company/" + TOKEN),
    ("workday", SUB + r"\.wd\d+\.myworkdayjobs\.com"),
    ("paylocity", r"recruiting\.paylocity\.com/recruiting/jobs/All/" + TOKEN),
    ("dover", r"app\.dover\.(?:com|io)/(?:jobs|apply)/" + TOKEN),
    ("zoho", SUB + r"\.zohorecruit\.com"),
    ("jobvite", r"jobs\.jobvite\.com/" + TOKEN),
    ("homerun", SUB + r"\.homerun\.co"),
    ("pinpoint", SUB + r"\.pinpointhq\.com"),
    ("linkedin", r"linkedin\.com/company/" + TOKEN + r"/jobs"),
]]
BAD_TOKENS = {
    "www", "api", "app", "apply", "jobs", "job", "embed", "boards", "assets", "static", "cdn",
    "help", "support", "js", "v1", "v0", "careers", "blog", "about", "go", "info", "status",
    "developers", "developer", "docs", "integrations", "marketplace", "resources", "en", "posting-api",
}

ATS_DOMAINS = re.compile(
    r"greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|recruitee\.com|breezy\.hr|smartrecruiters\.com|"
    r"bamboohr\.com|applytojob\.com|jobs\.personio\.|teamtailor\.com|ats\.rippling\.com|jobs\.gusto\.com|"
    r"wellfound\.com|myworkdayjobs\.com|recruiting\.paylocity\.com|app\.dover\.|zohorecruit\.com|"
    r"jobs\.jobvite\.com|homerun\.co|pinpointhq\.com|linkedin\.com/company/[^/]+/jobs",
    re.I,
)


def is_ats_url(url: str) -> bool:
    return bool(ATS_DOMAINS.search(url or ""))


def detect_ats(text: str) -> list[tuple[str, str]]:
    """Return unique (ats, token) pairs referenced in raw HTML/JS text."""
    found: list[tuple[str, str]] = []
    for name, pat in ATS_PATTERNS:
        for m in pat.finditer(text or ""):
            tok = m.group(1).strip(".-_").rstrip("\\")
            if not tok or tok.lower() in BAD_TOKENS or len(tok) > 80:
                continue
            key = (name, tok.lower() if name != "smartrecruiters" else tok)
            if key not in found:
                found.append(key)
    return found


def _loc(*parts) -> str:
    return ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


# --- Feed fetchers. Each returns list[Job] on success (possibly empty, meaning
# the board exists but has no openings) or None when the token is invalid. ---

async def _greenhouse(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    return [Job(j.get("title", ""), (j.get("location") or {}).get("name", ""),
                ", ".join(x.get("name", "") for x in j.get("departments") or []),
                j.get("absolute_url", "")) for j in d["jobs"]]


async def _lever(f: Fetcher, t: str):
    for host in ("api.lever.co", "api.eu.lever.co"):
        st, d = await f.get_json(f"https://{host}/v0/postings/{t}?mode=json")
        if isinstance(d, list):
            return [Job(j.get("text", ""), (j.get("categories") or {}).get("location", ""),
                        (j.get("categories") or {}).get("team", ""), j.get("hostedUrl", "")) for j in d]
    return None


async def _ashby(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t}")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    return [Job(j.get("title", ""), j.get("location", ""), j.get("department", ""),
                j.get("jobUrl", "")) for j in d["jobs"]]


async def _workable(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{t}")
    if not isinstance(d, dict) or "jobs" not in d:
        return None
    return [Job(j.get("title", ""), _loc(j.get("city"), j.get("state"), j.get("country")),
                j.get("department", ""), j.get("url") or j.get("shortlink", "")) for j in d["jobs"]]


async def _recruitee(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://{t}.recruitee.com/api/offers/")
    if not isinstance(d, dict) or "offers" not in d:
        return None
    return [Job(j.get("title", ""), j.get("location", ""), j.get("department", ""),
                j.get("careers_url", "")) for j in d["offers"]]


async def _breezy(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://{t}.breezy.hr/json")
    if not isinstance(d, list):
        return None
    return [Job(j.get("name", ""), (j.get("location") or {}).get("name", ""),
                j.get("department", ""), j.get("url", "")) for j in d]


async def _smartrecruiters(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://api.smartrecruiters.com/v1/companies/{t}/postings")
    if not isinstance(d, dict) or "content" not in d:
        return None
    if not d.get("totalFound"):
        return None  # API answers 200 + empty list even for non-existent companies
    out = []
    for j in d["content"]:
        loc = j.get("location") or {}
        out.append(Job(j.get("name", ""), _loc(loc.get("city"), loc.get("region"), loc.get("country")),
                       (j.get("department") or {}).get("label", ""),
                       f"https://jobs.smartrecruiters.com/{t}/{j.get('id', '')}"))
    return out


async def _bamboohr(f: Fetcher, t: str):
    st, d = await f.get_json(f"https://{t}.bamboohr.com/careers/list")
    if not isinstance(d, dict) or "result" not in d:
        return None
    out = []
    for j in d["result"]:
        loc = j.get("location") or {}
        out.append(Job(j.get("jobOpeningName", ""), _loc(loc.get("city"), loc.get("state")),
                       j.get("departmentLabel", ""), f"https://{t}.bamboohr.com/careers/{j.get('id', '')}"))
    return out


async def _personio(f: Fetcher, t: str):
    page = await f.get(f"https://{t}.jobs.personio.de/xml")
    if not page.ok or "<workzag-jobs" not in page.text:
        return None
    try:
        root = ET.fromstring(page.text.encode("utf-8"))
    except ET.ParseError:
        return None
    return [Job(p.findtext("name", ""), p.findtext("office", ""), p.findtext("department", ""),
                f"https://{t}.jobs.personio.de/job/{p.findtext('id', '')}") for p in root.iter("position")]


# Boards without a convenient JSON feed: fetch the hosted board page and keep
# links that match the board's job-detail URL shape.
HTML_BOARDS = {
    "jazzhr": ("https://{t}.applytojob.com/apply", re.compile(r"applytojob\.com/apply/[A-Za-z0-9]{6,}/", re.I)),
    "teamtailor": ("https://{t}.teamtailor.com/jobs", re.compile(r"teamtailor\.com/jobs/\d+", re.I)),
    "rippling": ("https://ats.rippling.com/{t}/jobs", re.compile(r"ats\.rippling\.com/[^/]+/jobs/[0-9a-f-]{8,}", re.I)),
    "gusto": ("https://jobs.gusto.com/boards/{t}", re.compile(r"jobs\.gusto\.com/postings/", re.I)),
    "zoho": ("https://{t}.zohorecruit.com/jobs/Careers", re.compile(r"zohorecruit\.com/jobs/Careers/\d+", re.I)),
    "homerun": ("https://{t}.homerun.co/", re.compile(r"homerun\.co/[a-z0-9-]+/?$", re.I)),
    "pinpoint": ("https://{t}.pinpointhq.com/", re.compile(r"pinpointhq\.com/(?:en/)?postings/", re.I)),
    "jobvite": ("https://jobs.jobvite.com/{t}/jobs", re.compile(r"jobs\.jobvite\.com/[^/]+/job/", re.I)),
}
GENERIC_LINK_TEXT = re.compile(r"^(apply( now)?|learn more|view( job| role| position| details)?|read more|details|see more|more|→|>)$", re.I)


async def _html_board(f: Fetcher, ats: str, t: str):
    tmpl, job_re = HTML_BOARDS[ats]
    page = await f.get(tmpl.format(t=t))
    if not page.ok:
        return None
    doc = LH.fromstring(page.text)
    doc.make_links_absolute(page.url)
    jobs, seen = [], set()
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if not job_re.search(href) or href in seen:
            continue
        title = " ".join(a.text_content().split())
        if not title or GENERIC_LINK_TEXT.match(title):
            continue
        seen.add(href)
        jobs.append(Job(title[:150], url=href))
    return jobs


FETCHERS = {
    "greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "workable": _workable,
    "recruitee": _recruitee, "breezy": _breezy, "smartrecruiters": _smartrecruiters,
    "bamboohr": _bamboohr, "personio": _personio,
}


def board_url(ats: str, t: str) -> str:
    return {
        "greenhouse": f"https://job-boards.greenhouse.io/{t}",
        "lever": f"https://jobs.lever.co/{t}",
        "ashby": f"https://jobs.ashbyhq.com/{t}",
        "workable": f"https://apply.workable.com/{t}",
        "recruitee": f"https://{t}.recruitee.com",
        "breezy": f"https://{t}.breezy.hr",
        "smartrecruiters": f"https://jobs.smartrecruiters.com/{t}",
        "bamboohr": f"https://{t}.bamboohr.com/careers",
        "personio": f"https://{t}.jobs.personio.de",
        "wellfound": f"https://wellfound.com/company/{t}/jobs",
        "linkedin": f"https://www.linkedin.com/company/{t}/jobs",
        "workday": f"https://{t}.wd1.myworkdayjobs.com",
        "paylocity": f"https://recruiting.paylocity.com/recruiting/jobs/All/{t}",
        "dover": f"https://app.dover.com/jobs/{t}",
    }.get(ats) or (HTML_BOARDS[ats][0].format(t=t) if ats in HTML_BOARDS else "")


async def fetch_ats_jobs(f: Fetcher, ats: str, token: str) -> list[Job] | None:
    """None = no usable feed / invalid token; [] = valid board with no openings."""
    if ats in FETCHERS:
        jobs = await FETCHERS[ats](f, token)
        conf = "high"
    elif ats in HTML_BOARDS:
        jobs = await _html_board(f, ats, token)
        conf = "medium"
    else:
        return None  # linkedin / wellfound / workday etc.: login- or JS-walled
    if jobs is None:
        return None
    for j in jobs:
        j.title = " ".join((j.title or "").split())
        j.source, j.confidence = ats, conf
    return [j for j in jobs if j.title]
