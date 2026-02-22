"""Capture live kidsmanagement API calls by intercepting the running app.

Launches a headed browser, loads familylink.google.com with your cookies,
then intercepts all requests to kidsmanagement-pa.  Navigate to a child's
screen time section and change a value – the full request + response is
printed automatically.

Usage:
    python scripts/capture_api_calls.py <cookies_file>

Example:
    python scripts/capture_api_calls.py "C:/Users/Joche/Downloads/familylink.google.com.cookies.json"
"""
from __future__ import annotations

import asyncio
import json
import sys

from playwright.async_api import Request, Response, async_playwright

COOKIES_FILE = sys.argv[1] if len(sys.argv) > 1 else "cookies.json"
TARGET_DOMAIN = "kidsmanagement-pa.clients6.google.com"


def load_cookies(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    result = []
    for c in raw:
        entry: dict = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        if "sameSite" in c:
            ss = c["sameSite"]
            # Playwright only accepts Strict, Lax, None
            if ss in ("Strict", "Lax", "None"):
                entry["sameSite"] = ss
        result.append(entry)
    return result


captured: list[dict] = []
pending_bodies: dict[int, bytes] = {}


async def on_request(request: Request) -> None:
    if TARGET_DOMAIN not in request.url:
        return

    try:
        body = request.post_data or ""
    except Exception:
        body = ""

    entry = {
        "id": id(request),
        "method": request.method,
        "url": request.url,
        "headers": dict(request.headers),
        "body": body,
        "response": None,
    }
    captured.append(entry)

    print(f"\n{'='*70}")
    print(f"► {request.method} {request.url[:120]}")
    important = ["authorization", "content-type", "x-goog-api-key",
                 "x-goog-authuser", "x-goog-ext-223261916-bin",
                 "x-goog-ext-202964622-bin", "x-goog-ext-198889211-bin",
                 "origin"]
    for h in important:
        if h in request.headers:
            val = request.headers[h]
            print(f"  {h}: {val[:80]}{'...' if len(val) > 80 else ''}")
    if body:
        print(f"  BODY: {body[:500]}")


async def on_response(response: Response) -> None:
    if TARGET_DOMAIN not in response.url:
        return

    try:
        text = await response.text()
    except Exception:
        text = "(could not read body)"

    # Find matching entry
    for entry in reversed(captured):
        if entry["url"] == response.url and entry["response"] is None:
            entry["response"] = {"status": response.status, "body": text}
            break

    print(f"\n◄ {response.status} {response.url[:120]}")
    if text:
        try:
            parsed = json.loads(text)
            print(json.dumps(parsed, indent=2)[:2000])
        except Exception:
            print(text[:500])


async def main() -> None:
    cookies = load_cookies(COOKIES_FILE)
    print(f"Loaded {len(cookies)} cookies from {COOKIES_FILE}")
    print(f"\nWaiting for requests to {TARGET_DOMAIN} ...\n")
    print("Instructions:")
    print("  1. The browser will open familylink.google.com")
    print("  2. Navigate to a child → Bildschirmzeit → Tageslimit")
    print("  3. Change the value and save")
    print("  4. The full request/response will be printed here")
    print("  5. Press Ctrl+C when done\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=50)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        await context.add_cookies(cookies)

        page = await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        print("Opening familylink.google.com ...")
        await page.goto("https://familylink.google.com/", wait_until="domcontentloaded")
        print(f"  title: {await page.title()}")
        print(f"  url:   {page.url}")
        print("\nBrowser is open – navigate to Bildschirmzeit → Tageslimit and change a value.")
        print("All kidsmanagement API calls will be captured here.")
        print("Press Ctrl+C to stop.\n")

        try:
            # Keep running until Ctrl+C
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        # Save all captured calls to file
        outfile = "scripts/captured_api_calls.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(captured, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(captured)} captured calls to {outfile}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
