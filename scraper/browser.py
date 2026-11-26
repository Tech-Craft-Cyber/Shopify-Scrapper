"""Optional headless-Chromium fallback for JS-rendered or bot-protected pages.

Enabled with --browser. Requires:  python -m playwright install chromium
"""
from __future__ import annotations

import asyncio

from .http import UA, Page


class Browser:
    def __init__(self, concurrency: int = 2):
        self._sem = asyncio.Semaphore(concurrency)
        self._pw = None
        self._browser = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def render(self, url: str, wait_ms: int = 3500) -> tuple[Page, list[str]]:
        """Return the rendered page plus every request URL it made (reveals ATS embeds)."""
        async with self._sem:
            ctx = await self._browser.new_context(user_agent=UA, locale="en-US", ignore_https_errors=True)
            requests: list[str] = []
            try:
                tab = await ctx.new_page()
                tab.on("request", lambda r: requests.append(r.url))
                resp = await tab.goto(url, wait_until="domcontentloaded", timeout=35000)
                await tab.wait_for_timeout(wait_ms)
                # Scroll to trigger lazy-loaded job widgets / iframes.
                for _ in range(4):
                    await tab.mouse.wheel(0, 2500)
                    await tab.wait_for_timeout(500)
                html = await tab.content()
                frames = [fr.url for fr in tab.frames if fr.url and fr.url != "about:blank"]
                # Job widgets often live in iframes (ATS embeds, custom apps): inline their DOM.
                extra = []
                for fr in tab.frames[1:]:
                    if fr.url.startswith("http"):
                        try:
                            extra.append(f'<section data-frame-src="{fr.url}">{await fr.content()}</section>')
                        except Exception:  # noqa: BLE001 - detached frames etc.
                            pass
                if extra:
                    html = html.replace("</body>", "".join(extra) + "</body>") if "</body>" in html else html + "".join(extra)
                return Page(tab.url, resp.status if resp else 200, html, "text/html"), requests + frames
            except Exception as e:  # noqa: BLE001 - playwright raises many types
                return Page(url, 0, "", "", error=f"browser: {type(e).__name__}: {e}"[:200]), requests
            finally:
                await ctx.close()
