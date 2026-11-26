"""Async HTTP helper: retries, per-host politeness, SSL fallback."""
from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BYTES = 6_000_000


@dataclass
class Page:
    url: str          # final URL after redirects
    status: int
    text: str
    content_type: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return not ct or "html" in ct or "xml" in ct

    def describe_failure(self) -> str:
        return self.error or f"HTTP {self.status}"


class Fetcher:
    def __init__(self, timeout: float = 15, retries: int = 1, per_host: int = 2):
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        common = dict(headers=HEADERS, follow_redirects=True, timeout=timeout, limits=limits)
        self._client = httpx.AsyncClient(**common)
        self._insecure = httpx.AsyncClient(verify=False, **common)
        self._retries = retries
        self._per_host = per_host
        self._host_sems: dict[str, asyncio.Semaphore] = {}

    async def close(self) -> None:
        await self._client.aclose()
        await self._insecure.aclose()

    def _sem(self, url: str) -> asyncio.Semaphore:
        host = urlsplit(url).netloc.lower()
        if host not in self._host_sems:
            self._host_sems[host] = asyncio.Semaphore(self._per_host)
        return self._host_sems[host]

    async def get(self, url: str, *, headers: dict | None = None) -> Page:
        client = self._client
        err = "unknown error"
        async with self._sem(url):
            attempt, rate_limited = 0, 0
            while attempt <= self._retries:
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 429 and rate_limited < 3:
                        # Rate limited: honour Retry-After (capped) and don't count it as a normal retry.
                        rate_limited += 1
                        ra = r.headers.get("retry-after", "")
                        await asyncio.sleep(min(30, int(ra)) if ra.isdigit() else 5 * rate_limited + random.random())
                        continue
                    if r.status_code in RETRY_STATUS and r.status_code != 429 and attempt < self._retries:
                        attempt += 1
                        await asyncio.sleep(1.5 * (2 ** attempt) + random.random())
                        continue
                    try:
                        text = r.content[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
                    except LookupError:  # bogus charset label, e.g. "utf8mb4"
                        text = r.content[:MAX_BYTES].decode("utf-8", errors="replace")
                    return Page(str(r.url), r.status_code, text, r.headers.get("content-type", ""))
                except httpx.ConnectError as e:
                    err = f"connect error: {e}"[:200]
                    if ("CERTIFICATE" in str(e) or "SSL" in str(e)) and client is self._client:
                        client = self._insecure  # retry once without verification
                        continue  # (doesn't consume a retry)
                    if "getaddrinfo" in str(e) or "Name or service" in str(e):
                        break  # DNS failure: retrying is pointless
                except httpx.TimeoutException:
                    err = "timeout"
                except (httpx.TooManyRedirects, httpx.RemoteProtocolError, httpx.UnsupportedProtocol,
                        httpx.InvalidURL, UnicodeError, ValueError) as e:
                    err = f"{type(e).__name__}: {e}"[:200]
                    break  # deterministic failure: retrying only wastes time
                except httpx.HTTPError as e:
                    err = f"{type(e).__name__}: {e}"[:200]
                attempt += 1
                if attempt <= self._retries:
                    await asyncio.sleep(1 + random.random())
        return Page(url, 0, "", "", error=err)

    async def get_json(self, url: str) -> tuple[int, Any]:
        """Return (status, parsed_json_or_None)."""
        page = await self.get(url, headers={"Accept": "application/json"})
        if not page.ok:
            return page.status, None
        try:
            return page.status, json.loads(page.text)
        except ValueError:
            return page.status, None
