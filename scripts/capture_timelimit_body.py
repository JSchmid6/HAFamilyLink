"""Intercept the timeLimit:update request body using Playwright.

Opens the Family Link daily limit page in a headed browser.
Captures the exact JSON payload when you manually change the daily limit.

Uses context.route() for reliable request interception (not page.on("request")).

Usage:
    python scripts/capture_timelimit_body.py <path/to/familylink.cookies.json>

Instructions:
    1. A Chrome browser opens at the Family Link daily limit page.
    2. Change Emilio's daily limit (e.g. increase/decrease weekday minutes).
    3. The script prints the captured request body and saves it to
       docs/timelimit_request_body.txt
    4. Close the browser window or press Ctrl+C to stop.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Route, Request


INTERCEPT_HOST = "kidsmanagement-pa.clients6.google.com"
TARGET_URL = "https://familylink.google.com/member/2/time_limits/daily_limit?authuser=0"
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "timelimit_request_body.txt"


def load_cookies(path: str) -> list[dict]:
    with open(path) as f:
        raw = json.load(f)
    samesite_map = {"strict": "Strict", "lax": "Lax", "no_restriction": "None"}
    result = []
    for c in raw:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".google.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
        }
        ss = c.get("sameSite", "lax").lower()
        cookie["sameSite"] = samesite_map.get(ss, "Lax")
        result.append(cookie)
    return result


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)
    captured: list[dict] = []
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"Opening: {TARGET_URL}")
    print("→ Change Emilio's daily limit in the browser window to capture the request.")
    print("→ Close the browser window when done.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
        )
        await context.add_cookies(cookies)

        # Use context.route to intercept ALL requests matching the pattern
        async def handle_route(route: Route) -> None:
            request = route.request
            method = request.method
            url = request.url

            if "timeLimit" in url or "appliedTimeLimits" in url:
                body_bytes = request.post_data_buffer
                body_str = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""

                print(f"\n{'='*70}")
                print(f"  METHOD: {method}")
                print(f"  URL: {url[:120]}")
                if body_str:
                    print(f"  BODY ({len(body_str)} chars): {body_str}")
                    print(f"  BODY bytes: {len(body_str.encode('utf-8'))}")
                else:
                    print(f"  BODY: (empty)")
                print(f"{'='*70}")

                if "timeLimit:update" in url and body_str:
                    entry = {
                        "method": method,
                        "url": url,
                        "body": body_str,
                        "body_bytes_len": len(body_str.encode("utf-8")),
                    }
                    captured.append(entry)
                    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, indent=2, ensure_ascii=False))
                        f.write("\n\n")
                    print(f"  ✓ Saved to {OUTPUT_FILE}")

            # Always continue the request
            await route.continue_()

        # Intercept all requests to the kidsmanagement API
        await context.route(f"**/{INTERCEPT_HOST}/**", handle_route)

        page = await context.new_page()

        # Also catch requests via page.on for redundancy
        def on_request_sync(request: Request) -> None:
            if INTERCEPT_HOST in request.url and "timeLimit:update" in request.url:
                body = request.post_data
                if body:
                    print(f"\n[page.on] BODY: {body}")

        page.on("request", on_request_sync)

        try:
            await page.goto(TARGET_URL, timeout=30_000)
            print("Page loaded. Waiting for interactions...\n")
            # Wait for the browser to be closed (page.close event)
            await page.wait_for_event("close", timeout=300_000)
        except Exception as e:
            if "Timeout" not in str(e) and "closed" not in str(e).lower():
                print(f"Error: {e}")
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    if captured:
        print(f"\n✓ Captured {len(captured)} timeLimit:update request(s).")
        for i, entry in enumerate(captured):
            print(f"\n  [{i+1}] {entry['body_bytes_len']} bytes")
            print(f"       Body: {entry['body']}")
    else:
        print("\n⚠ No timeLimit:update requests with body were captured.")
        print("  Make sure you changed the daily limit while the browser was open.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/capture_timelimit_body.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
