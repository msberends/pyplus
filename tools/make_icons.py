"""Render the home-screen app icons from pyplus/static/icons/icon.svg.

Run after changing the SVG:  uv run python tools/make_icons.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ICON_DIR = Path(__file__).resolve().parent.parent / "pyplus" / "static" / "icons"
SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


async def main() -> None:
    svg = (ICON_DIR / "icon.svg").read_text()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for name, size in SIZES.items():
            page = await browser.new_page(viewport={"width": size, "height": size})
            sized_svg = svg.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
            html = f"<html><body style='margin:0'>{sized_svg}</body></html>"
            await page.set_content(html)
            await page.screenshot(path=str(ICON_DIR / name), omit_background=False)
            await page.close()
            print(f"wrote {name} ({size}px)")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
