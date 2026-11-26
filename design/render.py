"""Render the HTML mockups in design/mockups/ to PNG images in design/.

    python design/render.py            # all mockups
    python design/render.py 01 03      # only files starting with these prefixes
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SRC = HERE / "mockups"
# name prefix -> (width, height, full_page)
SIZES = {"05a": (390, 844, False), "05b": (1440, 900, False)}
DEFAULT = (1440, 900, True)


def main() -> None:
    wanted = sys.argv[1:]
    files = sorted(p for p in SRC.glob("*.html") if not wanted or p.stem.startswith(tuple(wanted)))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for f in files:
            w, h, full = next((v for k, v in SIZES.items() if f.stem.startswith(k)), DEFAULT)
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
            page.goto(f.resolve().as_uri())
            page.wait_for_timeout(150)
            out = HERE / f"{f.stem}.png"
            page.screenshot(path=str(out), full_page=full)
            print(f"{out}  ({w}x{h}{' full page' if full else ''})")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
