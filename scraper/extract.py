"""Extract job openings from a careers page that is not an ATS feed."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from lxml import html as LH

from .ats import GENERIC_LINK_TEXT, Job, is_ats_url

# A job title must contain one of these role nouns.
ROLE_NOUN = re.compile(
    r"\b(developers?|engineers?|designers?|managers?|directors?|specialists?|strategists?|coordinators?|"
    r"lead|intern(ship)?s?|analysts?|associates?|producers?|copywriters?|writers?|consultants?|architects?|"
    r"executives?|representatives?|reps?|marketers?|editors?|administrators?|assistants?|officers?|"
    r"head of|vp|vice president|technicians?|scientists?|testers?|recruiters?|programmers?|artists?|"
    r"animators?|illustrators?|photographers?|videographers?|accountants?|bookkeepers?|controllers?|"
    r"planners?|buyers?|merchandisers?|expert|generalists?|owner|principal|apprentice(ship)?|trainee|"
    r"freelancers?|contractors?|advocates?|supervisors?|researchers?|technologists?|operator|"
    r"partner manager|sdr|bdr|cto|cmo|coo|cfo|qa)\b", re.I)
# Things that look like headings/sentences rather than titles.
NOT_TITLE = re.compile(
    r"\b(we|our|you|your|us|meet|about|why|how|what|benefits?|perks?|culture|values?|apply|hiring|"
    r"join|team members?|testimonials?|case stud(y|ies)|services?|solutions|clients?|blog|ask|opportunities|"
    r"resumes?|submit|contact|chat|since|certified|partners)\b|['’]s\b|[.?!:]$|^\d+$|&",
    re.I)
NO_OPENINGS = re.compile(
    r"\b(no|not any|zero) (current(ly)? |open |available |active )*(positions?|roles?|openings?|"
    r"vacanc(y|ies)|jobs?|job openings|opportunities)\b|nothing open|not (currently |actively )?hiring|"
    r"aren['’]?t (currently |actively )?hiring|no openings|all positions (are |have been )?filled|"
    r"there are (currently )?no (open |available )?(jobs|positions|roles|openings)",
    re.I)
JOB_PATH = re.compile(r"/(?:careers?|jobs?|positions?|openings?|vacanc(?:y|ies)|opportunities|join-us|join-our-team)/"
                      r"(?P<slug>[^/?#]+)", re.I)
JOB_PATH_STOP = {"apply", "page", "openings", "positions", "jobs", "search", "category", "location", "department",
                 "feed", "rss", "benefits", "culture", "life", "faq", "team", "about", "students", "internships"}
CONTAINER_HINT = re.compile(r"job|position|opening|role|vacanc|career-item|posting", re.I)


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def looks_like_title(text: str) -> bool:
    t = _norm(text)
    if not (3 <= len(t) <= 80) or len(t.split()) > 10:
        return False
    if " " not in t and "-" in t:  # URL slug, e.g. "data-architect-july-2026"
        return False
    if re.search(r"[·|$]|\bper (hour|year)\b", t):  # meta line: "Hybrid · Part-time · $16 to $19 per hour"
        return False
    return bool(ROLE_NOUN.search(t)) and not NOT_TITLE.search(t)


def _content_root(page_html: str, base_url: str):
    doc = LH.fromstring(page_html)
    doc.make_links_absolute(base_url, resolve_base_href=True)
    return doc


def jsonld_jobs(doc) -> list[Job]:
    jobs: list[Job] = []

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            typ = node.get("@type")
            if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                loc = node.get("jobLocation") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                if isinstance(addr, str):
                    addr = {"addressLocality": addr}
                where = ", ".join(str(addr.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")
                                  if isinstance(addr.get(k), str) and addr.get(k))
                if node.get("jobLocationType") == "TELECOMMUTE":
                    where = (where + " (Remote)").strip()
                jobs.append(Job(_norm(node.get("title", "")), where, "", node.get("url", ""), "jsonld", "high"))
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    for s in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            walk(json.loads(s.text_content()))
        except ValueError:
            continue
    return [j for j in jobs if j.title]


def _nearest_heading(el) -> str:
    node = el
    for _ in range(4):
        node = node.getparent()
        if node is None:
            break
        hs = node.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//strong")
        for h in hs:
            if looks_like_title(h.text_content()):
                return _norm(h.text_content())
    return ""


def link_jobs(doc, page_url: str) -> list[Job]:
    """Anchors pointing at individual job pages (own site or ATS)."""
    jobs = []
    page_path = urlsplit(page_url).path.rstrip("/")
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if not href.startswith("http"):
            continue
        parts = urlsplit(href)
        text = _norm(a.text_content())
        m = JOB_PATH.search(parts.path)
        own_job_page = (m and m.group("slug").lower() not in JOB_PATH_STOP and parts.path.rstrip("/") != page_path
                        and ("-" in m.group("slug") or m.group("slug").isdigit()))
        ats_job_page = is_ats_url(href) and re.search(r"/(jobs?|postings?|apply|o|j|careers)/[^/]+", parts.path)
        if not (own_job_page or ats_job_page):
            continue
        location = ""
        if GENERIC_LINK_TEXT.match(text) or not text:
            title = _nearest_heading(a) or (m.group("slug").replace("-", " ").title() if own_job_page else "")
        else:
            # Card-style links hold "Title / Location · Type / blurb" in separate elements.
            title, location = _split_card(a)
        title = re.sub(r"\s*(apply( now)?|learn more|view( job| role)?|read more|→|>)\s*$", "", title, flags=re.I)
        if not looks_like_title(title):
            continue
        jobs.append(Job(title, location=location, url=href.split("#")[0], source="html-link",
                        confidence="medium" if ats_job_page or own_job_page else "low"))
    return jobs


LOCATION_HINT = re.compile(r"\b(remote|hybrid|on-?site|in-office|worldwide|anywhere|united states|usa|"
                           r"canada|uk)\b|,\s*[A-Z]{2}\b", re.I)


def _split_card(a) -> tuple[str, str]:
    """Return (title, location) from an anchor whose text spans several elements."""
    chunks = [_norm(t) for t in a.itertext() if _norm(t)]
    for i, c in enumerate(chunks):
        if looks_like_title(c):
            loc = next((d for d in chunks[i + 1:i + 4] if LOCATION_HINT.search(d) and len(d) <= 80), "")
            return c, loc
    return _norm(a.text_content())[:120], ""


def heading_jobs(doc) -> list[Job]:
    """Role-like headings / bold labels (e.g. a 'Current Openings' list)."""
    jobs = []
    els = doc.xpath("//h2|//h3|//h4|//h5|//h6|//li/strong|//li/b|//summary|//dt")
    for el in els:
        cls = " ".join(filter(None, [el.get("class"), (el.getparent().get("class") if el.getparent() is not None else None)]))
        text = _norm(el.text_content())
        if looks_like_title(text):
            jobs.append(Job(text, source="html-heading", confidence="medium" if CONTAINER_HINT.search(cls) else "low"))
    return jobs


OPENINGS_HEAD = re.compile(r"(open|current|featured|available|latest)\s*(positions|roles|openings|jobs|opportunities)|"
                           r"job openings|we['’]?re hiring|now hiring|join (us|our team)|careers?$", re.I)
BLOCK_TAGS = {"p", "a", "li", "div", "span", "h3", "h4", "h5", "h6", "strong", "b", "td", "button"}


def section_jobs(doc) -> list[Job]:
    """Role-like short texts that follow an 'Open positions'-style heading."""
    jobs = []
    for h in doc.xpath("//h1|//h2|//h3|//h4|//p[string-length(normalize-space()) < 40]"):
        if not OPENINGS_HEAD.search(_norm(h.text_content())):
            continue
        for el in h.xpath("following::*[position() <= 120]"):
            if el.tag in ("h1", "h2") and not OPENINGS_HEAD.search(_norm(el.text_content())):
                break  # next major section
            if el.tag not in BLOCK_TAGS or len(el) > 3:
                continue
            text = _norm(el.text_content())
            if looks_like_title(text):
                jobs.append(Job(text, source="html-section", confidence="medium"))
    return jobs


def strip_chrome(doc) -> None:
    for bad in doc.xpath("//script|//style|//noscript|//svg|//nav|//header|//footer|//form"
                         "|//*[@role='navigation']|//*[@id='shopify-section-header']|//*[@id='shopify-section-footer']"):
        bad.drop_tree()


def visible_text(doc) -> str:
    return _norm(" ".join(doc.itertext()))


def dedupe(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        key = (re.sub(r"\W+", " ", j.title.lower()).strip(), j.location.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def page_fingerprint(page_html: str, page_url: str) -> str:
    """Hash of the careers page's visible text (ignores scripts, nav, footer)."""
    import hashlib
    try:
        doc = _content_root(page_html, page_url)
    except Exception:  # noqa: BLE001 - unparsable page
        return ""
    strip_chrome(doc)
    text = re.sub(r"\d{1,2}:\d{2}\s*(AM|PM)?", "", visible_text(doc), flags=re.I)  # live clocks etc.
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _dedupe_title(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        key = re.sub(r"\W+", " ", j.title.lower()).strip()
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def _drop_nested_duplicates(jobs: list[Job]) -> list[Job]:
    """'Creative Senior Digital Designer' (card text) vs 'Senior Digital Designer' (its title): keep the shorter."""
    titles = [j.title.lower() for j in jobs]
    keep = []
    for j, t in zip(jobs, titles):
        if any(o != t and o in t and len(o) >= 6 for o in titles) and j.source != "html-link":
            continue
        keep.append(j)
    return keep


def extract_jobs(page_html: str, page_url: str) -> tuple[list[Job], bool, str]:
    """Return (jobs, says_no_openings, visible_text)."""
    doc = _content_root(page_html, page_url)
    jl = jsonld_jobs(doc)
    strip_chrome(doc)
    text = visible_text(doc)
    no_openings = bool(NO_OPENINGS.search(text))
    if jl:
        return dedupe(jl), no_openings, text
    links = link_jobs(doc, page_url)
    heads = heading_jobs(doc)
    # Links come first so the copy that has a URL + location wins; the same title
    # found again as a heading is a duplicate regardless of (missing) location.
    jobs = _dedupe_title(links + section_jobs(doc) + heads)
    jobs = _drop_nested_duplicates(jobs)
    # A page that explicitly says "no openings" and only yields low-confidence
    # heading matches is almost always listing teams/departments, not roles.
    if no_openings and all(j.confidence == "low" for j in jobs):
        jobs = []
    return jobs, no_openings, text
