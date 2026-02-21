"""Non-interactive browser interception of families.google.com API calls.

Loads families.google.com with stored cookies, captures all external API
requests to a JSON file for analysis. Run and wait ~30 seconds.

Usage: .venv/Scripts/python.exe scripts/intercept_headless.py
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

COOKIE_FILE = r"C:\Users\Joche\Downloads\myaccount.google.com.cookies (4).json"
OUTPUT_FILE = r"C:\DEV\HAFamilyLink\scripts\captured_requests.json"
WAIT_SECONDS = 20


async def main() -> None:
    cookies_raw = json.load(open(COOKIE_FILE))
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

    captured: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        await ctx.add_cookies(pw_cookies)

        page = await ctx.new_page()

        def on_request(req):
            url = req.url
            if any(x in url for x in [
                "kidsmanagement", "familylink", "googleapis.com", "families.google",
                "accounts.google", "play.google"
            ]):
                captured.append({
                    "method": req.method,
                    "url": url,
                    "post_data": req.post_data,
                    "headers": dict(req.headers),
                })

        page.on("request", on_request)

        # Navigate to families.google.com
        print("Loading families.google.com ...")
        try:
            await page.goto("https://families.google.com", wait_until="networkidle", timeout=20000)
        except Exception as e:
            print(f"  Warning during load: {e}")

        await page.wait_for_timeout(3000)

        # Try to navigate to screen time section 
        current_url = page.url
        print(f"Current URL: {current_url}")

        # Check page title
        title = await page.title()
        print(f"Page title: {title}")

        # Try clicking on any child link
        print("Looking for children links...")
        child_links = []
        try:
            links = await page.query_selector_all("a[href*='child'], a[href*='member'], [data-child], button")
            for el in links[:20]:
                text = await el.inner_text()
                href = await el.get_attribute("href") or ""
                if text.strip():
                    child_links.append(f"text='{text.strip()[:40]}' href='{href[:60]}'")
            print(f"  Found elements: {child_links[:10]}")
        except Exception as e:
            print(f"  Error: {e}")

        # Try direct navigation to screen time
        for child_id in ["112452138243419815198", "115307393794918034742", "105266986367418000092"]:
            for path in [
                f"/u/0/families/supervised_user/{child_id}/screentime",
                f"/families/supervised_user/{child_id}/screentime",
                f"/families/supervised_user/{child_id}",
            ]:
                try:
                    print(f"\nTrying https://families.google.com{path}")
                    await page.goto(f"https://families.google.com{path}", wait_until="networkidle", timeout=10000)
                    url_after = page.url
                    title_after = await page.title()
                    print(f"  -> URL: {url_after}")
                    print(f"  -> Title: {title_after}")
                    await page.wait_for_timeout(2000)
                    break
                except Exception as e:
                    print(f"  Error: {e}")

        await page.wait_for_timeout(3000)
        await browser.close()

    print(f"\n=== Captured {len(captured)} API requests ===")
    significant = [r for r in captured if any(
        x in r["url"] for x in ["kidsmanagement", "familylink.google", "families.google"]
    )]
    for req in significant:
        print(f"\n[{req['method']}] {req['url']}")
        if req.get("post_data"):
            print(f"  POST: {req['post_data'][:300]}")

    # Save all captured requests
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(captured, f, indent=2, ensure_ascii=False)
    print(f"\nAll requests saved to: {OUTPUT_FILE}")


asyncio.run(main())
