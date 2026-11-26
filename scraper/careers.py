"""Find an agency's careers page.

Order: (1) scored links on the homepage, (2) sitemap.xml, (3) probing common
paths. Probe hits are validated because many sites answer unknown paths with
a 200 copy of the homepage ("soft 404").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from lxml import html as LH

from .ats import is_ats_url
from .http import Fetcher, Page

STRONG_TEXT = re.compile(
    r"^(careers?|jobs?|job openings|join (us|our team|the team|the crew)|we['’]?re hiring|now hiring|hiring|"
    r"open (positions|roles)|current (openings|opportunities)|career opportunities|job opportunities|vacancies|"
    r"work (for|at) [\w&' -]{1,30}|(careers|jobs) (at|with|for) [\w&' -]{1,30}|join [\w&' -]{1,20} team|employment|opportunities)[\s!.→>»›-]*$", re.I)
_CAREER_SEGMENT = re.compile(
    r"^([\w-]*(careers?|jobs|job-openings|joinus|join-us|join-our-team|join-the-team|work-for-us|"
    r"open-positions|open-roles|vacancies|employment)[\w-]*|(we-?re-|now-)?hiring)(\.html?|\.php|\.aspx)?$", re.I)
# Long slugs are articles ("hiring-a-shopify-expert-in-the-usa", "...-hiring-checklist"), not careers pages.
_ARTICLE_SLUG = re.compile(r"^[^-]+(-[^-]+){4,}$|\b(hire|hiring-a|checklist|guide|how-to|expert|cost)\b", re.I)


class _CareerSegment:
    @staticmethod
    def match(segment: str):
        if _ARTICLE_SLUG.search(segment.replace("_", "-")):
            return None
        return _CAREER_SEGMENT.match(segment)


CAREER_SEGMENT = _CareerSegment()
EXCLUDE_PATH = re.compile(r"/(blogs?|news|posts?|articles?|case-studies|portfolio|products?|collections|tags?|"
                          r"category|press|insights|resources|podcast)/", re.I)
CAREER_TITLE = re.compile(r"career|jobs?\b|join|hiring|open (roles|positions)|work (with|for|at)|vacanc|"
                          r"opportunit|employment|team", re.I)
SOFT_404 = re.compile(r"\b(404|page not found|not found|doesn['’]?t exist|cannot be found)\b", re.I)
PROBE_PATHS = ["/careers", "/jobs", "/pages/careers", "/join-us", "/join", "/about/careers",
               "/company/careers", "/join-our-team", "/work-with-us", "/pages/jobs", "/hiring"]
MAIL_RE = re.compile(r"mailto:((?:careers?|jobs|hiring|hr|recruit\w*|talent|people|work)@[\w.-]+)", re.I)

NON_COMPANY_HOSTS = re.compile(
    r"(^|\.)(instagram|facebook|fb|linkedin|twitter|x|tiktok|youtube|youtu|pinterest|calendly|upwork|fiverr|"
    r"linktr|linktree|behance|dribbble|github|medium|clutch|wa|whatsapp|t|threads|tidycal|cal|"
    r"hubspot|google|forms\.gle|bit|beacons|carrd)\.(com|co|be|ly|ee|me|io|net|gle|app)$", re.I)


@dataclass
class Discovery:
    careers_url: str = ""
    method: str = ""          # homepage-link | sitemap | probe | ats-link
    ats_links: list[str] | None = None
    careers_email: str = ""
    candidates: list[str] | None = None
    page: Page | None = None  # the fetched careers page (avoids refetching)


def base_domain(host: str) -> str:
    host = host.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net", "ac", "gov"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(a: str, b: str) -> bool:
    return base_domain(urlsplit(a).netloc) == base_domain(urlsplit(b).netloc)


def is_non_company_site(url: str) -> bool:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return bool(NON_COMPANY_HOSTS.search(host)) or host.endswith(("sites.google.com",))


def score_link(href: str, text: str, home_url: str) -> int:
    parts = urlsplit(href)
    if parts.scheme not in ("http", "https"):
        return 0
    if is_ats_url(href):
        return 100
    if not same_site(href, home_url) or EXCLUDE_PATH.search(parts.path + "/"):
        return 0
    segs = [s for s in parts.path.split("/") if s]
    path_hit = any(CAREER_SEGMENT.match(s) for s in segs[-2:]) and len(segs) <= 3
    text = " ".join(text.split())
    text_hit = bool(STRONG_TEXT.match(text)) and len(text) <= 40
    if path_hit and text_hit:
        return 90
    if path_hit:
        return 70
    if text_hit and segs:  # e.g. "Careers" -> /culture
        return 60
    return 0


def homepage_candidates(home: Page) -> tuple[list[tuple[int, str]], list[str], str]:
    doc = LH.fromstring(home.text)
    doc.make_links_absolute(home.url, resolve_base_href=True)
    scored: dict[str, int] = {}
    ats_links: list[str] = []
    email = ""
    for a in doc.iter("a"):
        href = (a.get("href") or "").strip()
        if href.lower().startswith("mailto:"):
            m = MAIL_RE.match(href)
            if m and not email:
                email = m.group(1)
            continue
        href = href.split("#")[0]
        if not href:
            continue
        text = a.text_content() or a.get("aria-label") or a.get("title") or ""
        s = score_link(href, text, home.url)
        if s >= 100 and href not in ats_links:
            ats_links.append(href)
        elif s and urlsplit(href).path.rstrip("/") != urlsplit(home.url).path.rstrip("/"):
            scored[href.rstrip("/")] = max(scored.get(href.rstrip("/"), 0), s)
    ranked = sorted(((s, u) for u, s in scored.items()), key=lambda x: (-x[0], len(x[1])))
    return ranked, ats_links, email


def looks_like_careers_page(page: Page, home_url: str) -> bool:
    if not page.ok or not page.is_html or not page.text:
        return False
    final = urlsplit(page.url)
    if final.path.rstrip("/") in ("", "/") or page.url.rstrip("/") == home_url.rstrip("/"):
        return False  # redirected to the homepage
    try:
        doc = LH.fromstring(page.text)
    except Exception:
        return False
    title = " ".join(doc.xpath("//title//text()"))
    heads = " ".join(" ".join(h.text_content().split()) for h in doc.xpath("//h1|//h2")[:6])
    if SOFT_404.search(title) or SOFT_404.search(heads[:200]):
        return False
    return bool(CAREER_TITLE.search(title) or CAREER_TITLE.search(heads) or CAREER_SEGMENT.match(
        (final.path.rstrip("/").split("/") or [""])[-1]))


async def from_sitemap(f: Fetcher, home_url: str) -> list[str]:
    root = f"{urlsplit(home_url).scheme}://{urlsplit(home_url).netloc}"
    page = await f.get(root + "/sitemap.xml")
    if not page.ok or "<loc>" not in page.text:
        return []
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", page.text)
    hits = [u for u in locs if _career_loc(u, home_url)]
    if not hits and "<sitemapindex" in page.text:
        children = [u for u in locs if re.search(r"page|sitemap_pages|sitemap-pages|post_type", u, re.I)][:3] or locs[:2]
        for child in children:
            cp = await f.get(child)
            if cp.ok:
                hits += [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", cp.text) if _career_loc(u, home_url)]
    return sorted(set(hits), key=len)[:3]


def _career_loc(u: str, home_url: str) -> bool:
    p = urlsplit(u)
    segs = [s for s in p.path.split("/") if s]
    return (same_site(u, home_url) and bool(segs) and len(segs) <= 3 and not EXCLUDE_PATH.search(p.path + "/")
            and CAREER_SEGMENT.match(segs[-1]) is not None)


async def discover(f: Fetcher, home: Page, get=None, max_probes: int = len(PROBE_PATHS)) -> Discovery:
    """`get` overrides how pages are fetched (e.g. via the browser for bot-blocked sites)."""
    get = get or f.get
    d = Discovery()
    ranked, d.ats_links, d.careers_email = homepage_candidates(home)
    d.candidates = [u for _, u in ranked[:5]]
    for score, url in ranked[:3]:
        page = await get(url)
        # score >= 60 means an explicit "Careers"/"Jobs" link text or a /careers-style path.
        if page.ok and page.is_html and (score >= 60 or looks_like_careers_page(page, home.url)):
            d.careers_url, d.method, d.page = page.url, "homepage-link", page
            return d
    for url in await from_sitemap(f, home.url):
        page = await get(url)
        if looks_like_careers_page(page, home.url):
            d.careers_url, d.method, d.page = page.url, "sitemap", page
            return d
    root = f"{urlsplit(home.url).scheme}://{urlsplit(home.url).netloc}"
    failures = 0
    for path in PROBE_PATHS[:max_probes]:
        page = await get(urljoin(root, path))
        # Redirect loops, rate limits, dropped connections: the site won't cooperate, stop probing.
        failures = failures + 1 if (page.status in (0, 429) or page.status >= 500) else 0
        if failures >= 2:
            break
        if looks_like_careers_page(page, home.url):
            d.careers_url, d.method, d.page = page.url, "probe", page
            return d
    if d.ats_links:
        d.careers_url, d.method = d.ats_links[0], "ats-link"
    return d
