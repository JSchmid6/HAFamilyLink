"""Probe endpoints to find the 'Tageslimit' (daily screen time limit) write endpoint.

The GET appliedTimeLimits response shows the limit as ["CAEQBg", 6, 2, 90, ...].
We need to find which POST/PATCH endpoint WRITES this value.

Key insight:
- timeLimitOverrides:batchCreate creates TEMPORARY overrides (lock/bonus)
- The persistent daily limit uses a DIFFERENT endpoint

Usage:
    python scripts/probe_endpoints.py <path/to/familylink.cookies.json>
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time

import aiohttp

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
CHILD_ID = "112452138243419815198"
EMILIO_DEV = "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq"
EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"


def load_cookies(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {c["name"]: c["value"] for c in data}


def make_headers(cookies: dict) -> dict:
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    ts = str(int(time.time() * 1000))
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return {
        "Authorization": f"SAPISIDHASH {ts}_{digest}",
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json+protobuf",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "x-goog-ext-223261916-bin": EXT_223,
        "x-goog-ext-202964622-bin": EXT_202,
    }


async def probe(session: aiohttp.ClientSession, cookies: dict, method: str, url: str, payload=None) -> None:
    h = make_headers(cookies)
    try:
        if method == "GET":
            async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
                status = r.status
                body = await r.text()
        else:
            async with session.post(url, json=payload, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
                status = r.status
                body = await r.text()
    except Exception as e:
        print(f"  ERR {method} {url.replace(BASE, '')}: {e}")
        return

    label = url.replace(BASE, "").replace(f"/people/{CHILD_ID}", "/{child}")
    if status == 200:
        print(f"\n  ✅ {status} {method} {label}")
        try:
            print(json.dumps(json.loads(body), indent=2)[:800])
        except Exception:
            print(body[:500])
    elif status in (404, 405, 501):
        print(f"  {status} {method} {label}")
    else:
        msg = ""
        try:
            msg = json.loads(body).get("error", {}).get("message", "")
        except Exception:
            msg = body[:200]
        print(f"  {status} {method} {label}: {msg[:150]}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_endpoints.py <cookies.json>")
        sys.exit(1)
    cookies = load_cookies(sys.argv[1])

    # What we know:
    # - GET appliedTimeLimits returns: body[child_entry][2] = ["CAEQBg", 6, 2, 90, ...]
    # - CAEQBg in base64 = bytes \x08\x01\x10\x06 → proto: field1=1, field2=6
    #   → likely schedule_type=1 (DAILY), day_of_week=6 (Saturday in some encoding)
    # - The persistent daily limit needs a different endpoint than timeLimitOverrides:batchCreate

    # Payloads:
    # Try minimal JSPB payloads; 90→120 to detect a limit change later
    set_90  = [None, None, [[EMILIO_DEV, None, None, 90]]]
    set_120 = [None, None, [[EMILIO_DEV, None, None, 120]]]
    dev_set = [None, None, [[None, None, EMILIO_DEV, None, 120]]]
    simple  = [CHILD_ID, [[EMILIO_DEV, 90]]]

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as s:

        print("=== 1. GET endpoints ===")
        for path in (
            f"/people/{CHILD_ID}/timeLimits",
            f"/people/{CHILD_ID}/timeLimitOverrides",
            f"/people/{CHILD_ID}/screenTimeLimits",
            f"/people/{CHILD_ID}/deviceTimeLimits",
            f"/people/{CHILD_ID}/scheduledTimeLimits",
            f"/people/{CHILD_ID}/timeLimitSchedules",
            f"/people/{CHILD_ID}/devices/{EMILIO_DEV}/timeLimits",
            f"/people/{CHILD_ID}/devices/{EMILIO_DEV}/screenTimeLimits",
        ):
            await probe(s, cookies, "GET", BASE + path)

        print("\n=== 2. POST – batchCreate variants ===")
        post_pairs = [
            (f"/people/{CHILD_ID}/timeLimits:batchCreate",           set_90),
            (f"/people/{CHILD_ID}/timeLimits:batchUpdate",           set_90),
            (f"/people/{CHILD_ID}/timeLimits:update",                set_90),
            (f"/people/{CHILD_ID}/screenTimeLimits:batchCreate",     set_90),
            (f"/people/{CHILD_ID}/screenTimeLimits:batchUpdate",     set_90),
            (f"/people/{CHILD_ID}/deviceTimeLimits:batchCreate",     set_90),
            (f"/people/{CHILD_ID}/deviceTimeLimits:batchUpdate",     set_90),
            (f"/people/{CHILD_ID}/scheduledTimeLimits:batchCreate",  set_90),
            (f"/people/{CHILD_ID}/scheduledTimeLimits:batchUpdate",  set_90),
            (f"/people/{CHILD_ID}/timeLimitSchedules:batchCreate",   set_90),
            (f"/people/{CHILD_ID}/timeLimitSchedules:batchUpdate",   set_90),
            (f"/people/{CHILD_ID}/dailyTimeLimits:batchCreate",      set_90),
            (f"/people/{CHILD_ID}/dailyTimeLimits:batchUpdate",      set_90),
            (f"/people/{CHILD_ID}/devices/{EMILIO_DEV}/timeLimits:update",  [None, 90]),
            (f"/people/{CHILD_ID}/devices/{EMILIO_DEV}/timeLimits:batchUpdate", [None, 90]),
        ]
        for url, payload in post_pairs:
            await probe(s, cookies, "POST", BASE + url, payload)

        print("\n=== 3. More patterns – families scope ===")
        # tducret uses families/mine/apps:updateRestrictions → maybe devices:updateRestrictions?
        for path, payload in [
            ("/families/mine/devices:updateTimeLimits",       [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/devices:batchUpdate",            [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/devices:updateRestrictions",     [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/timeLimits:batchCreate",         [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/timeLimits:batchUpdate",         [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/screenTimeLimits:batchUpdate",   [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
            ("/families/mine/deviceTimeLimits:batchUpdate",   [CHILD_ID, [[EMILIO_DEV, None, 90]]]),
        ]:
            await probe(s, cookies, "POST", BASE + path, payload)

        print("\n=== 4. batchCreate with higher action values ===")
        # Maybe action=3..6 has special meaning (set scheduled limit?  set daily limit?)
        for action in (3, 4, 5, 6):
            await probe(s, cookies, "POST",
                        f"{BASE}/people/{CHILD_ID}/timeLimitOverrides:batchCreate",
                        [None, None, [[None, None, action, EMILIO_DEV, None, 90]]])

        print("\n=== 5. Re-check appliedTimeLimits ===")
        await probe(s, cookies, "GET",
                    f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
                    "?capabilities=TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME")


if __name__ == "__main__":
    asyncio.run(main())
