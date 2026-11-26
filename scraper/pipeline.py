"""Per-partner pipeline: profile -> website -> careers page -> open roles."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

from lxml import html as LH

from . import ats as ATS
from .browser import Browser
from .careers import STRONG_TEXT, discover, is_non_company_site, same_site
from .directory import Partner, fetch_profile
from .extract import extract_jobs, page_fingerprint
from .http import Fetcher, Page

# Final status per partner (one of):
ROLES_FOUND = "roles_found"
NO_OPENINGS = "careers_page_no_openings"
UNPARSED = "careers_page_roles_unclear"     # careers page exists, nothing parseable -> manual check
NO_CAREERS = "no_careers_page"
NO_WEBSITE = "no_website"
NON_COMPANY = "non_company_site"            # instagram / calendly / upwork ...
UNREACHABLE = "site_unreachable"
RATE_LIMITED = "rate_limited"               # HTTP 429: transient, not cached -> retried on next run
PROFILE_ERR = "profile_error"

FOLLOW_TEXT = re.compile(r"(view|see|browse|explore)( all| our)? (open |current )?(jobs|roles|positions|openings|"
                         r"opportunities)|open (positions|roles)|current openings|job openings|apply (now|here|today)", re.I)
SCRIPT_HINT = re.compile(r"career|job|greenhouse|lever|ashby|workable|recruit|position|opening|vacanc", re.I)


@dataclass
class Result:
    partner: dict
    status: str = ""
    final_url: str = ""
    careers_url: str = ""
    discovery_method: str = ""
    ats: str = ""
    ats_board: str = ""
    careers_email: str = ""
    careers_hash: str = ""   # fingerprint of the careers page text (detects changes between runs)
    used_browser: bool = False
    notes: str = ""
    jobs: list[dict] = field(default_factory=list)


def _ats_from_page(page: Page) -> list[tuple[str, str]]:
    return ATS.detect_ats(page.text) + ATS.detect_ats(page.url)


async def _ats_from_scripts(f: Fetcher, page: Page) -> list[tuple[str, str]]:
    """Some sites load their job board from a first-party JS file (e.g. greenhouse-jobs.js)."""
    try:
        doc = LH.fromstring(page.text)
    except Exception:
        return []
    doc.make_links_absolute(page.url)
    srcs = [s for s in doc.xpath("//script/@src") if same_site(s, page.url) and SCRIPT_HINT.search(urlsplit(s).path)]
    found: list[tuple[str, str]] = []
    for src in srcs[:4]:
        js = await f.get(src)
        if js.ok:
            found += [x for x in ATS.detect_ats(js.text) if x not in found]
    return found


async def _jobs_from_ats(f: Fetcher, hits: list[tuple[str, str]], res: Result) -> list[ATS.Job] | None:
    """Try each detected board; first valid board wins (None if none valid)."""
    for name, token in hits:
        jobs = await ATS.fetch_ats_jobs(f, name, token)
        if jobs is not None:
            res.ats, res.ats_board = name, ATS.board_url(name, token)
            return jobs
    # Remember unfetchable boards (e.g. LinkedIn) so users can check manually.
    if hits and not res.ats:
        res.ats, res.ats_board = hits[0][0], ATS.board_url(*hits[0])
    return None


def _follow_link(page: Page) -> str:
    """A 'View open positions' style link on a careers landing page."""
    try:
        doc = LH.fromstring(page.text)
    except Exception:
        return ""
    doc.make_links_absolute(page.url)
    for a in doc.iter("a"):
        href = (a.get("href") or "").split("#")[0]
        text = " ".join(a.text_content().split())
        if href.startswith("http") and href.rstrip("/") != page.url.rstrip("/") and (
                FOLLOW_TEXT.search(text) or (STRONG_TEXT.match(text) and "/careers/" in href)):
            if same_site(href, page.url) or ATS.is_ats_url(href):
                return href
    return ""


def _needs_browser(page: Page, text: str) -> bool:
    low = page.text.lower()
    return (len(text) < 600 or "<iframe" in low or "__next" in low or "data-reactroot" in low
            or "grnhse" in low or "ng-app" in low or "id=\"app\"" in low or "id=\"root\"" in low)


async def analyse_careers_page(f: Fetcher, br: Browser | None, page: Page,
                               res: Result) -> tuple[list[ATS.Job], bool]:
    """Return (jobs, page_says_no_openings)."""
    hits = _ats_from_page(page)
    hits += [h for h in await _ats_from_scripts(f, page) if h not in hits]
    ats_jobs = await _jobs_from_ats(f, hits, res)
    if ats_jobs is not None:
        res.notes = f"{res.ats} board has {len(ats_jobs)} open roles" if ats_jobs else f"{res.ats} board is empty"
        return ats_jobs, not ats_jobs

    jobs, no_open, text = extract_jobs(page.text, page.url)
    if not jobs and not no_open:
        nxt = _follow_link(page)
        if nxt:
            np = await f.get(nxt)
            if np.ok:
                hits2 = [h for h in _ats_from_page(np) if h not in hits]
                ats_jobs = await _jobs_from_ats(f, hits2, res)
                if ats_jobs is not None:
                    res.careers_url = np.url
                    return ats_jobs, not ats_jobs
                jobs, no_open, text = extract_jobs(np.text, np.url)
                if jobs or no_open:
                    res.careers_url = np.url

    if not jobs and not no_open and br and _needs_browser(page, text):
        rendered, requests = await br.render(page.url)
        res.used_browser = True
        if rendered.ok:
            hits3 = []
            for u in requests:
                hits3 += [h for h in ATS.detect_ats(u) if h not in hits3 and h not in hits]
            hits3 += [h for h in _ats_from_page(rendered) if h not in hits3 and h not in hits]
            ats_jobs = await _jobs_from_ats(f, hits3, res)
            if ats_jobs is not None:
                return ats_jobs, not ats_jobs
            jobs, no_open, text = extract_jobs(rendered.text, rendered.url)

    if no_open and not jobs:
        res.notes = "page says there are no open positions"
    return jobs, no_open


async def process(partner: Partner, f: Fetcher, br: Browser | None) -> Result:
    res = Result(partner={})
    err = await fetch_profile(f, partner)
    res.partner = asdict(partner)
    if err:
        res.status, res.notes = PROFILE_ERR, err
        return res
    if not partner.website:
        res.status = NO_WEBSITE
        return res
    if is_non_company_site(partner.website):
        res.status, res.notes = NON_COMPANY, urlsplit(partner.website).netloc
        return res

    home = await f.get(partner.website)
    if not home.ok:  # retry the www / non-www twin before giving up
        parts = urlsplit(partner.website)
        twin = parts.netloc[4:] if parts.netloc.startswith("www.") else "www." + parts.netloc
        alt = await f.get(f"{parts.scheme}://{twin}/")
        if alt.ok:
            home = alt
    blocked = False
    if (not home.ok or not home.text) and br:
        home, _ = await br.render(partner.website)
        res.used_browser = blocked = True
    if not home.ok or not home.text:
        res.status = RATE_LIMITED if home.status == 429 else UNREACHABLE
        res.notes = home.describe_failure()
        return res
    res.final_url = home.url

    async def browser_get(url: str) -> Page:
        return (await br.render(url, wait_ms=1500))[0]

    # Bot-protected sites (403 to plain HTTP) must be crawled with the browser throughout.
    d = await discover(f, home, get=browser_get, max_probes=4) if blocked else await discover(f, home)
    res.careers_email = d.careers_email
    if not d.careers_url and br and len(home.text) < 20000:
        # JS-only homepage: render it and look for careers links again.
        rendered, _ = await br.render(home.url)
        res.used_browser = True
        if rendered.ok:
            d = await discover(f, rendered)
            res.careers_email = res.careers_email or d.careers_email
    if not d.careers_url:
        res.status = NO_CAREERS
        res.notes = "no careers link, sitemap entry, or common careers path"
        if res.careers_email:
            res.notes += f"; careers email: {res.careers_email}"
        return res

    res.careers_url, res.discovery_method = d.careers_url, d.method
    page = d.page or await f.get(d.careers_url)
    if not page.ok and br:
        page, _ = await br.render(d.careers_url)
        res.used_browser = True
    if not page.ok:
        res.status, res.notes = UNPARSED, f"careers page fetch failed: {page.describe_failure()}"
        return res

    res.careers_hash = page_fingerprint(page.text, page.url)
    jobs, no_open = await analyse_careers_page(f, br, page, res)
    res.jobs = [asdict(j) for j in jobs]
    if jobs:
        res.status = ROLES_FOUND
    elif no_open:
        res.status = NO_OPENINGS
    else:
        res.status = UNPARSED
        if not res.notes:
            res.notes = "careers page found but no roles could be parsed (may be email-only or JS-rendered)"
    return res
