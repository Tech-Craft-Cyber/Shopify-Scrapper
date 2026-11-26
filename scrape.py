"""Scrape open roles from agencies listed in the Shopify Partner Directory.

Examples:
    python scrape.py                                   # store_building, US, all partners
    python scrape.py --limit 30                        # quick trial on the first 30
    python scrape.py --handles darkroom,anatta1        # specific partners
    python scrape.py --browser                         # headless-Chromium fallback for JS sites
    python scrape.py --service custom_apps --location CA
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from scraper.directory import fetch_listing, listing_url
from scraper.http import Fetcher
from scraper.output import write_all
from scraper.pipeline import Result, process

TRANSIENT = {"timeout", "error", "rate_limited"}  # never cached, so a re-run retries them


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--service", default="store_building", help="directory service slug (default: store_building)")
    ap.add_argument("--location", default="US", help="primary-location country code; '' for all (default: US)")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N partners")
    ap.add_argument("--handles", default="", help="comma-separated partner handles to process")
    ap.add_argument("--concurrency", type=int, default=8, help="partners processed in parallel (default: 8)")
    ap.add_argument("--browser", action="store_true", help="use headless Chromium for JS/blocked pages")
    ap.add_argument("--refresh", action="store_true", help="ignore cached per-partner results")
    ap.add_argument("--timeout", type=float, default=0,
                    help="max seconds per partner (default: 150, or 300 with --browser)")
    ap.add_argument("--out", default="output", help="output directory (default: output)")
    return ap.parse_args()


async def main() -> int:
    args = parse_args()
    args.timeout = args.timeout or (300 if args.browser else 150)
    # Playwright navigations cancelled by a per-partner timeout can surface as noisy
    # "Future exception was never retrieved" messages at shutdown; they are harmless.
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda lp, ctx: None if "TargetClosed" in repr(ctx.get("exception"))
                               else lp.default_exception_handler(ctx))
    out = Path(args.out)
    cache = out / "cache" / f"{args.service}_{args.location or 'ALL'}"
    cache.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher()
    browser = None
    if args.browser:
        from scraper.browser import Browser
        browser = Browser()
        try:
            await browser.start()
        except Exception as e:  # noqa: BLE001
            print(f"! Browser unavailable ({e}).\n  Run: python -m playwright install chromium\n  Continuing without it.")
            browser = None

    try:
        print(f"Listing: {listing_url(args.service, args.location)}")
        partners = await fetch_listing(fetcher, args.service, args.location)
        print(f"Found {len(partners)} partners")
        if args.handles:
            wanted = {h.strip() for h in args.handles.split(",") if h.strip()}
            partners = [p for p in partners if p.handle in wanted]
            missing = wanted - {p.handle for p in partners}
            if missing:
                print(f"! Not in this listing: {', '.join(sorted(missing))}")
        if args.limit:
            partners = partners[: args.limit]

        results: list[dict] = []
        sem = asyncio.Semaphore(args.concurrency)
        done = 0
        started = time.time()

        async def run(p):
            nonlocal done
            cfile = cache / f"{p.handle}.json"
            if cfile.exists() and not args.refresh:
                r = json.loads(cfile.read_text(encoding="utf-8"))
            else:
                async with sem:
                    try:
                        res = await asyncio.wait_for(process(p, fetcher, browser), args.timeout)
                    except asyncio.TimeoutError:
                        res = Result(partner=asdict(p), status="timeout", notes=f"exceeded {args.timeout}s")
                    except Exception as e:  # noqa: BLE001 - never let one site kill the run
                        res = Result(partner=asdict(p), status="error", notes=f"{type(e).__name__}: {e}"[:300])
                r = asdict(res)
                if r["status"] not in TRANSIENT:
                    cfile.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            done += 1
            n = len(r["jobs"])
            print(f"[{done}/{len(partners)}] {r['partner']['name'][:40]:40} {r['status']:28} "
                  f"{(str(n) + ' roles') if n else '':9} {r.get('careers_url') or ''}", flush=True)
            results.append(r)

        await asyncio.gather(*(run(p) for p in partners))
    finally:
        await fetcher.close()
        if browser:
            await browser.close()

    paths = write_all(results, out)
    stats = Counter(r["status"] for r in results)
    print(f"\nDone in {time.time() - started:.0f}s. Status summary:")
    for k, v in stats.most_common():
        print(f"  {k:30} {v}")
    print(f"  total roles: {sum(len(r['jobs']) for r in results)}")
    for k, p in paths.items():
        print(f"  -> {p}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
