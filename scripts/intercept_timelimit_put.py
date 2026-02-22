"""
Intercept the actual timeLimit:update POST request body sent by the browser.

Uses the existing Chrome user profile (already logged in) via launch_persistent_context.
Chrome must be fully closed before running this script!

Usage: .venv\Scripts\python.exe scripts\intercept_timelimit_put.py
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

CHILD_ID = "112452138243419815198"

TARGET_URL = "https://familylink.google.com/member/2/time_limits/daily_limit?authuser=0"
OUTPUT_FILE = Path("docs/timelimit_request_body.txt")


COOKIE_PATH = Path.home() / "Downloads" / "familylink.google.com.cookies.json"


def build_storage_state(cookie_path: Path) -> dict:
    """Convert exported cookies JSON into Playwright storage_state format."""
    raw = json.loads(cookie_path.read_text())
    samesite_map = {
        "strict": "Strict",
        "lax": "Lax",
        "no_restriction": "None",
        "unspecified": "Lax",
    }
    cookies = []
    for c in raw:
        domain = c.get("domain", ".google.com")
        # Playwright needs domain WITHOUT leading dot for exact match,
        # but WITH leading dot for wildcard (subdomains). Keep as-is.
        name = c.get("name", "")
        value = c.get("value", "")
        if not name or not value:
            continue
        ss_raw = str(c.get("sameSite", "lax")).lower()
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": c.get("path", "/"),
            "secure": c.get("secure", name.startswith("__Secure-")),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": samesite_map.get(ss_raw, "Lax"),
        })
    return {"cookies": cookies, "origins": []}


async def main() -> None:
    cookie_path = Path(sys.argv[1]) if len(sys.argv) > 1 else COOKIE_PATH
    print(f"Loading cookies from: {cookie_path}")
    storage = build_storage_state(cookie_path)
    print(f"Loaded {len(storage['cookies'])} cookies\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=storage)

        page = await context.new_page()
        captured: list[dict] = []

        def on_request(req):
            if "timeLimit:update" in req.url:
                try:
                    body = req.post_data or ""
                except Exception:
                    body = ""
                captured.append({"url": req.url, "body": body, "headers": dict(req.headers)})
                print(f"\n{'='*60}")
                print("CAPTURED timeLimit:update!")
                print(f"  Body ({len(body)} chars): {body}")
                print(f"{'='*60}\n")

        context.on("request", on_request)

        print(f"Navigating to: {TARGET_URL}")
        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation warning: {e}")

        print("\n>>> CHANGE EMILIO'S DAILY LIMIT NOW <<<")
        print("Waiting up to 90 seconds for you to make a change…")

        for _ in range(180):
            await asyncio.sleep(0.5)
            if captured:
                break

        if not captured:
            print("\nNo request captured. Try manually changing the daily limit.")
        else:
            OUTPUT_FILE.parent.mkdir(exist_ok=True)
            for i, cap in enumerate(captured):
                print(f"\n--- Request {i+1} ---")
                print(f"URL: {cap['url'][:120]}")
                print(f"Body: {cap['body']}")
                print(f"Content-Type: {cap['headers'].get('content-type', 'N/A')}")
            # Save to file
            OUTPUT_FILE.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
            print(f"\nSaved to {OUTPUT_FILE}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
