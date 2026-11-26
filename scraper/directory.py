"""Shopify Partner Directory: listing page + partner profile pages.

Findings from inspecting the site (Nov 2026):
* /partners/directory/services/<service>?location=<CC> is server-rendered and
  contains *every* matching partner in one response (US store_building = 919
  links, positions 1..919). There is no pagination to follow.
* Each partner link is <a data-component-name="partner-profile-link"
  data-component-extra-partner_handle=... data-component-extra-position=...>.
* The profile page /partners/directory/partner/<handle> exposes the agency's
  own site as <a aria-label="Visit website (opens in a new tab)" href=...>.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from lxml import html as LH

from .http import Fetcher

BASE = "https://www.shopify.com/partners/directory"
TIERS = {"Platinum", "Premier", "Plus", "Select"}


@dataclass
class Partner:
    position: int
    handle: str
    name: str
    partner_id: str = ""
    profile_url: str = ""
    tier: str = ""
    location: str = ""
    team_size: str = ""
    partner_since: str = ""
    website: str = ""
    linkedin: str = ""
    extra: dict = field(default_factory=dict)


def listing_url(service: str, location: str | None, extra: dict | None = None) -> str:
    params = {}
    if location:
        params["location"] = location
    params.update(extra or {})
    q = f"?{urlencode(params)}" if params else ""
    return f"{BASE}/services/{service}{q}"


async def fetch_listing(fetcher: Fetcher, service: str, location: str | None,
                        extra: dict | None = None) -> list[Partner]:
    url = listing_url(service, location, extra)
    page = await fetcher.get(url)
    if not page.ok:
        raise RuntimeError(f"Listing fetch failed ({page.describe_failure()}): {url}")
    doc = LH.fromstring(page.text)
    seen: dict[str, Partner] = {}
    for a in doc.xpath('//a[@data-component-name="partner-profile-link"]'):
        handle = a.get("data-component-extra-partner_handle") or a.get("href", "").rstrip("/").split("/")[-1]
        if not handle or handle in seen:
            continue
        pos = a.get("data-component-extra-position") or "0"
        seen[handle] = Partner(
            position=int(pos) if pos.isdigit() else 0,
            handle=handle,
            name=" ".join(a.text_content().split()),
            partner_id=a.get("data-component-extra-partner_id", ""),
            profile_url=f"{BASE}/partner/{handle}",
        )
    if not seen:
        raise RuntimeError("No partner links found - the directory markup may have changed.")
    return sorted(seen.values(), key=lambda p: p.position)


def clean_url(url: str) -> str:
    """Drop utm_* tracking params and fragments."""
    parts = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path or "/", urlencode(q), ""))


def parse_profile(partner: Partner, html: str) -> None:
    doc = LH.fromstring(html)
    site = doc.xpath('//a[starts-with(@aria-label, "Visit website")]/@href')
    if site:
        partner.website = clean_url(site[0])
    li = doc.xpath('//a[@aria-label="LinkedIn"]/@href')
    if li:
        partner.linkedin = li[0]
    for bad in doc.xpath("//script|//style|//svg"):
        bad.drop_tree()
    main = doc.xpath("//main")
    items = [t.strip() for t in (main[0] if main else doc).itertext() if t.strip()]

    def after(label: str) -> str:
        try:
            return items[items.index(label) + 1]
        except (ValueError, IndexError):
            return ""

    if len(items) > 1 and items[1] in TIERS:
        partner.tier = items[1]
    partner.location = after("Primary location")
    partner.team_size = after("Estimated team size")
    partner.partner_since = after("Partner since")


async def fetch_profile(fetcher: Fetcher, partner: Partner) -> str | None:
    """Fill profile fields in place. Returns an error string on failure."""
    page = await fetcher.get(partner.profile_url)
    if not page.ok:
        return f"profile fetch failed: {page.describe_failure()}"
    parse_profile(partner, page.text)
    return None
