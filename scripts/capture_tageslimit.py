"""Capture the exact network request sent when changing the Tageslimit in Family Link.

This script opens a Playwright browser with an EXISTING cookie session, navigates to
the Family Link supervision page, and uses a request interceptor to log all API calls.
When you change the Tageslimit in the UI and click 'Save', the intercepted request
will reveal the exact endpoint + payload format.

Prerequisites:
    pip install playwright
    playwright install chromium

Usage:
    python scripts/capture_tageslimit.py <path/to/familylink.google.com.cookies.json>

Then in the opened browser:
    1. Navigate to the child's screen time / Tageslimit settings
    2. Change the daily limit
    3. Click Save / Speichern
    4. Look at the terminal output for the captured request
"""
from __future__ import annotations

import asyncio
import json
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright not installed. Run:  pip install playwright && playwright install chromium")
    sys.exit(1)

CAPTURE_URL_FRAGMENT = "kidsmanagement"
FAMILYLINK_URL = "https://familylink.google.com"


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/capture_tageslimit.py <cookies.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        cookies_raw = json.load(f)

    # Convert to Playwright cookie format
    pw_cookies = []
    for c in cookies_raw:
        pw_c: dict = {
            "name":   c["name"],
            "value":  c["value"],
            "domain": c.get("domain", ".google.com"),
            "path":   c.get("path", "/"),
        }
        if c.get("expirationDate"):
            pw_c["expires"] = float(c["expirationDate"])
        if c.get("secure"):
            pw_c["secure"] = True
        if c.get("httpOnly"):
            pw_c["httpOnly"] = True
        if c.get("sameSite") in ("Strict", "Lax", "None"):
            pw_c["sameSite"] = c["sameSite"]
        pw_cookies.append(pw_c)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context()
        await context.add_cookies(pw_cookies)

        page = await context.new_page()

        # ── Intercept all API requests ──────────────────────────────────────
        captured: list[dict] = []

        async def on_request(request) -> None:
            url = request.url
            if CAPTURE_URL_FRAGMENT in url:
                method = request.method
                headers = dict(request.headers)
                body_bytes = request.post_data
                print(f"\n{'='*70}")
                print(f"  {method} {url}")
                print(f"  Content-Type: {headers.get('content-type','')}")
                if body_bytes:
                    print(f"  Body: {body_bytes[:1000]}")
                captured.append({"method": method, "url": url, "body": body_bytes})

        async def on_response(response) -> None:
            url = response.url
            if CAPTURE_URL_FRAGMENT in url:
                status = response.status
                try:
                    body = await response.text()
                    print(f"  → {status} {url.split('?')[0].split('/')[-1]}: {body[:500]}")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"Opening {FAMILYLINK_URL} …")
        print("Navigate to Tageslimit settings, change the value, click Save.")
        print("Watch this terminal for the intercepted POST request.\n")
        print("Press Ctrl+C to stop.\n")

        await page.goto(FAMILYLINK_URL, wait_until="domcontentloaded")

        # Keep running until user stops
        try:
            await asyncio.sleep(300)  # 5 minutes
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass

        if captured:
            print(f"\n\nCaptured {len(captured)} kidsmanagement requests.")
            with open("scripts/captured_requests.json", "w") as f:
                json.dump(captured, f, indent=2)
            print("Saved to scripts/captured_requests.json")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
