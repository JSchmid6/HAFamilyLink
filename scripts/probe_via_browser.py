"""Probe appliedTimeLimits and timeLimitOverrides:batchCreate via Playwright.

Makes fetch() calls from inside the authenticated families.google.com browser
context, so all dynamic auth headers (x-goog-ext-*) are automatically included.

Usage:
    python scripts/probe_via_browser.py <cookies_file>

Example:
    python scripts/probe_via_browser.py "C:/Users/Joche/Downloads/myaccount.google.com.cookies (5).json"
"""
from __future__ import annotations

import asyncio
import json
import sys

from playwright.async_api import async_playwright

COOKIES_FILE = sys.argv[1] if len(sys.argv) > 1 else "cookies.json"
BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"

# Child ID captured from browser DevTools
CHILD_ID = "112452138243419815198"

# Device IDs from previous probing
DEVICE_IDS = [
    "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq",  # Emilio SM-X200
    "aannnppamndo3hpm5l75fc35uyf5efgsiibwjsaexvkq",   # Ronja VOG-L29
    "aannnppapjsjabgpoeqyqegjrlhxm44rghua23rzkacq",   # Ronja SM-X200
    "aannnppanqkemfw6nyffszirutt3aoyltrhqhkkvud3a",   # Lennard SM-X200
]


def load_cookies(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # Convert to Playwright format
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
            entry["sameSite"] = c["sameSite"]
        result.append(entry)
    return result


async def fetch_in_browser(page, url: str, method: str = "GET", body: dict | None = None) -> dict:
    """Execute a fetch() call inside the browser page context with SAPISIDHASH auth."""
    js = """
    async ([url, method, body]) => {
        // Compute SAPISIDHASH using Web Crypto API
        async function sapisidhash(sapisid, origin) {
            const ts = Date.now().toString();
            const msg = ts + ' ' + sapisid + ' ' + origin;
            const enc = new TextEncoder().encode(msg);
            const hashBuf = await crypto.subtle.digest('SHA-1', enc);
            const hashArr = Array.from(new Uint8Array(hashBuf));
            const hashHex = hashArr.map(b => b.toString(16).padStart(2, '0')).join('');
            return 'SAPISIDHASH ' + ts + '_' + hashHex;
        }

        // Read SAPISID from cookies (not httpOnly)
        function getCookie(name) {
            const m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '=([^;]*)'));
            return m ? decodeURIComponent(m[1]) : null;
        }

        const sapisid = getCookie('__Secure-3PAPISID') || getCookie('SAPISID') || '';
        const origin = 'https://families.google.com';
        const auth = await sapisidhash(sapisid, origin);

        const opts = {
            method: method,
            headers: {
                'Content-Type': 'application/json+protobuf',
                'Authorization': auth,
                'X-Goog-AuthUser': '0',
                'X-Goog-Api-Key': 'AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw',
            }
        };
        if (body !== null) {
            opts.body = JSON.stringify(body);
        }

        try {
            const resp = await fetch(url, opts);
            const text = await resp.text();
            let parsed = null;
            try { parsed = JSON.parse(text); } catch(e) {}
            return {
                status: resp.status,
                statusText: resp.statusText,
                text: text,
                json: parsed,
                sapisid_used: sapisid ? sapisid.substring(0, 8) + '...' : '(none)',
                auth_used: auth.substring(0, 40) + '...',
            };
        } catch(e) {
            return { error: e.toString(), status: -1 };
        }
    }
    """
    result = await page.evaluate(js, [url, method, body])
    return result


async def main() -> None:
    cookies = load_cookies(COOKIES_FILE)
    print(f"Loaded {len(cookies)} cookies")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()

        # Inject cookies
        await context.add_cookies(cookies)

        page = await context.new_page()

        # Navigate to the authenticated families.google.com app
        print("\nNavigating to families.google.com...")
        try:
            await page.goto("https://families.google.com/u/0/", wait_until="domcontentloaded", timeout=20000)
            print(f"  page title: {await page.title()}")
            print(f"  final url:  {page.url}")
        except Exception as e:
            print(f"  navigation: {e}")

        # ── GET appliedTimeLimits ──────────────────────────────────────────────
        url_limits = (
            f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
            f"?capabilities=TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
        )
        print(f"\n{'='*60}")
        print(f"GET appliedTimeLimits  child={CHILD_ID}")
        result = await fetch_in_browser(page, url_limits, "GET")
        print(f"Status: {result.get('status')} {result.get('statusText','')}")
        print(f"  SAPISID used: {result.get('sapisid_used','?')}")
        print(f"  Auth: {result.get('auth_used','?')}")
        if result.get("json"):
            print(json.dumps(result["json"], indent=2))
        else:
            print(result.get("text", "")[:1000])
            if "error" in result:
                print(f"Error: {result['error']}")

        # Also try without capabilities param
        url_limits_bare = f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
        print(f"\n--- bare (no capabilities param) ---")
        result2 = await fetch_in_browser(page, url_limits_bare, "GET")
        print(f"Status: {result2.get('status')} {result2.get('statusText','')}")
        if result2.get("json"):
            print(json.dumps(result2["json"], indent=2))
        else:
            print(result2.get("text", "")[:500])

        # ── POST timeLimitOverrides:batchCreate ───────────────────────────────
        url_batch = f"{BASE}/people/{CHILD_ID}/timeLimitOverrides:batchCreate"
        print(f"\n{'='*60}")
        print(f"POST timeLimitOverrides:batchCreate  child={CHILD_ID}")

        # Try different payload structures
        for label, payload in [
            ("empty {}", {}),
            ("timeLimitOverrides[]", {"timeLimitOverrides": [{"deviceId": DEVICE_IDS[0], "dailyLimitInMs": 7200000}]}),
            ("requests[]", {"requests": [{"deviceId": DEVICE_IDS[0], "timeLimitOverride": {"dailyLimitInMs": 7200000}}]}),
        ]:
            print(f"\n-- payload: {label} --")
            result = await fetch_in_browser(page, url_batch, "POST", payload)
            status = result.get("status")
            print(f"Status: {status} {result.get('statusText','')}")
            if status not in (401, 403):
                if result.get("json"):
                    print(json.dumps(result["json"], indent=2))
                else:
                    print(result.get("text", "")[:800])
            if status == 200:
                print("  ✓ SUCCESS! This is the right payload format.")
                break

        await browser.close()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
