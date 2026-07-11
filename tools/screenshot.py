"""
Screenshot tool for development — captures pages of the running PyPLUS app.

Credentials and app URL come from .screenshot.env (gitignored):
    EMAIL=your@email.nl
    PASSWORD=yourpassword
    APP_URL=https://your-app-url

Session storage is cached to .screenshot_session.json so re-login is skipped
on subsequent runs (valid until the NiceGUI session expires).

Usage:
    uv run python tools/screenshot.py                   # all pages
    uv run python tools/screenshot.py cockpit dishes    # specific pages
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".screenshot.env"
SESSION_FILE = ROOT / ".screenshot_session.json"
SCREENSHOT_DIR = ROOT / "screenshots"

PAGES = {
    "login": "/login",
    "weekmenu": "/weekmenu",
    "promos": "/promos",
    "staples": "/staples",
    "cart": "/cart",
    "autopilot": "/autopilot",
    "dishes": "/dishes",
    "settings": "/settings",
    "cockpit": "/cockpit",
}

# How long to wait for the page to settle after navigation (ms)
PAGE_SETTLE_MS = 2500
# How long to wait for login to complete — Plus.nl OAuth takes ~20s
LOGIN_TIMEOUT_MS = 60_000


def _load_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        sys.exit(
            f"Missing {ENV_FILE.name} — create it with EMAIL=, PASSWORD=, APP_URL= "
            f"(see tools/screenshot.py docstring)"
        )
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    for required in ("EMAIL", "PASSWORD", "APP_URL"):
        if required not in env:
            sys.exit(f".screenshot.env is missing {required}=")
    return env


async def _take_screenshots(pages: list[str]) -> None:
    from playwright.async_api import async_playwright

    env = _load_env()
    base_url = env["APP_URL"].rstrip("/")
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs: dict = {
            "viewport": {"width": 1400, "height": 900},
            "locale": "nl-NL",
        }

        # Restore saved session if available
        if SESSION_FILE.exists():
            print("Restoring saved session…")
            context_kwargs["storage_state"] = str(SESSION_FILE)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # Check if the session is still valid by hitting weekmenu
        if SESSION_FILE.exists():
            await page.goto(f"{base_url}/weekmenu", wait_until="networkidle")
            if "/login" in page.url or "/weekmenu" not in page.url:
                # If the email field is visible it's the manual login form — no auto-login.
                # Otherwise the app's remember-me auto-login is running; wait up to 20s.
                has_form = await page.get_by_label("E-mailadres", exact=False).count() > 0
                if not has_form:
                    print("Auto-login in progress — waiting up to 20s…")
                    try:
                        await page.wait_for_url(f"{base_url}/weekmenu", timeout=20_000)
                        await page.wait_for_timeout(PAGE_SETTLE_MS)
                        await context.storage_state(path=str(SESSION_FILE))
                        print("Auto-login succeeded.")
                    except Exception:
                        has_form = True  # fall through to manual login
                if has_form:
                    print("Session expired — logging in again…")
                    SESSION_FILE.unlink(missing_ok=True)
                    await context.close()
                    context = await browser.new_context(
                        viewport={"width": 1400, "height": 900},
                        locale="nl-NL",
                    )
                    page = await context.new_page()
                    await _login(page, base_url, env)
                    await context.storage_state(path=str(SESSION_FILE))
                    print(f"Session saved to {SESSION_FILE.name}")
            else:
                print("Session still valid.")
        else:
            await _login(page, base_url, env)
            await context.storage_state(path=str(SESSION_FILE))
            print(f"Session saved to {SESSION_FILE.name}")

        # Take screenshots
        for name in pages:
            path = PAGES.get(name)
            if path is None:
                print(f"Unknown page '{name}' — skipping (known: {', '.join(PAGES)})")
                continue
            print(f"Screenshotting /{name}…")
            await page.goto(f"{base_url}{path}", wait_until="networkidle")
            await page.wait_for_timeout(PAGE_SETTLE_MS)
            out = SCREENSHOT_DIR / f"{name}.png"
            await page.screenshot(path=str(out), full_page=True)
            print(f"  -> {out.relative_to(ROOT)}")

        await browser.close()


async def _login(page, base_url: str, env: dict[str, str]) -> None:
    print("Navigating to login page…")
    await page.goto(f"{base_url}/login", wait_until="networkidle")
    await page.wait_for_timeout(500)

    # Fill credentials
    await page.get_by_label("E-mailadres", exact=False).fill(env["EMAIL"])
    await page.get_by_label("Wachtwoord", exact=False).fill(env["PASSWORD"])

    print("Submitting login form — waiting for Plus.nl OAuth (~20s)…")
    await page.get_by_role("button").filter(has_text="Inloggen").click()

    # Wait for redirect to weekmenu (Plus.nl OAuth + session setup)
    await page.wait_for_url(f"{base_url}/weekmenu", timeout=LOGIN_TIMEOUT_MS)
    await page.wait_for_timeout(PAGE_SETTLE_MS)
    print("Login successful.")


def main() -> None:
    requested = sys.argv[1:] if len(sys.argv) > 1 else list(PAGES)
    unknown = [p for p in requested if p not in PAGES]
    if unknown:
        print(f"Unknown pages: {', '.join(unknown)}")
        print(f"Available: {', '.join(PAGES)}")
        sys.exit(1)
    print(f"Pages: {', '.join(requested)}")
    asyncio.run(_take_screenshots(requested))


if __name__ == "__main__":
    main()
