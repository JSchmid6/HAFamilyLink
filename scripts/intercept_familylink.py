"""Intercept Family Link API calls by navigating families.google.com with real cookies.

This intercepts all XHR/fetch requests to find the overall screen time endpoint.
Usage: .venv/Scripts/python.exe scripts/intercept_familylink.py
"""
import asyncio
import json

from playwright.async_api import async_playwright

COOKIE_FILE = r"C:\Users\Joche\Downloads\myaccount.google.com.cookies (4).json"
CHILD_NAME = "Emilio"  # navigate to this child


async def main() -> None:
    cookies_raw = json.load(open(COOKIE_FILE))
    # Convert Cookie-Editor format → Playwright format
    pw_cookies = []
    for c in cookies_raw:
        expires = c.get("expires")
        same_site = c.get("sameSite", "Lax")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "expires": int(expires) if expires else -1,
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": same_site,
        })

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        ctx = await browser.new_context()
        await ctx.add_cookies(pw_cookies)

        captured: list[dict] = []

        def on_request(req):
            url = req.url
            if any(x in url for x in ["kidsmanagement", "familylink", "googleapis.com"]):
                captured.append({
                    "method": req.method,
                    "url": url,
                    "post_data": req.post_data,
                })

        page = await ctx.new_page()
        page.on("request", on_request)

        print("Navigating to families.google.com ...")
        await page.goto("https://families.google.com", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        print("=== Captured API calls on page load ===")
        for r in captured:
            print(f"  [{r['method']}] {r['url']}")
            if r["post_data"]:
                print(f"       POST: {r['post_data'][:200]}")
        captured.clear()

        # Try to navigate to the first child
        print(f"\nLooking for {CHILD_NAME}...")
        try:
            links = await page.query_selector_all("a, button")
            for link in links:
                text = await link.inner_text()
                if CHILD_NAME.lower() in text.lower():
                    print(f"  Clicking: {text.strip()[:60]}")
                    await link.click()
                    await page.wait_for_timeout(3000)
                    break
        except Exception as e:
            print(f"  Could not find child link: {e}")

        print("\n=== Captured API calls after child navigation ===")
        for r in captured:
            print(f"  [{r['method']}] {r['url']}")
            if r["post_data"]:
                print(f"       POST: {r['post_data'][:200]}")

        print("\n>>> Browser open – navigate to 'Screen time' / 'Bildschirmzeit' settings")
        print(">>> Set or change the daily screen time limit")
        print(">>> Then press ENTER here to see captured requests")
        input()

        print("\n=== Captured after manual interaction ===")
        for r in captured:
            print(f"  [{r['method']}] {r['url']}")
            if r["post_data"]:
                print(f"       POST: {r['post_data'][:300]}")

        await browser.close()


asyncio.run(main())
