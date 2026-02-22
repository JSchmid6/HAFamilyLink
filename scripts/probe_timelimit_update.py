"""Probe the timeLimit:update endpoint to discover the JSPB payload format.

From DevTools capture in docs/timelimits.txt we know:
- Endpoint: PUT /people/{child_id}/timeLimit:update
- Called via POST with ?$httpMethod=PUT
- Content-Type: application/json+protobuf

This script tries various JSPB payload structures to find what works.
We test with safe values (current known limit = 90 min) to avoid changing
anything unintentionally.

Usage:
    python scripts/probe_timelimit_update.py <path/to/familylink.cookies.json>
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from urllib.parse import urlencode

import aiohttp

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
CHILD_ID = "112452138243419815198"
EMILIO_DEV = "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq"
EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

# Current known limit for Emilio = 90 min/day
# We test with 90 to make it a no-op change
TEST_MINUTES = 90


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


async def try_payload(
    session: aiohttp.ClientSession,
    cookies: dict,
    label: str,
    payload: object,
) -> None:
    """Try a single payload against timeLimit:update and print the result."""
    # Google proxies PUT via POST + ?$httpMethod=PUT
    url = f"{BASE}/people/{CHILD_ID}/timeLimit:update?$httpMethod=PUT"
    body = json.dumps(payload)
    h = make_headers(cookies)
    print(f"\n--- {label} ---")
    print(f"  Payload: {body}")
    try:
        async with session.post(
            url,
            headers=h,
            data=body,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            status = r.status
            text = await r.text()
            print(f"  Status: {status}")
            if text:
                # Try pretty-print if JSON
                try:
                    print(f"  Body: {json.dumps(json.loads(text), indent=2)[:800]}")
                except Exception:
                    print(f"  Body: {text[:400]}")
            else:
                print("  Body: (empty)")
    except Exception as exc:
        print(f"  ERROR: {exc}")


async def get_current_limits(session: aiohttp.ClientSession, cookies: dict) -> None:
    """Fetch appliedTimeLimits to see the current state before/after."""
    url = (
        f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
        "?capabilities=TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
    )
    h = make_headers(cookies)
    async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
        text = await r.text()
    print("\n=== Current appliedTimeLimits (raw) ===")
    try:
        data = json.loads(text)
    except Exception:
        print(f"  (parse error) {text[:200]}")
        return
    print(f"  type={type(data).__name__}")
    if isinstance(data, dict):
        devices = data.get("appliedTimeLimits", [])
        for dev in devices:
            dev_id = dev.get("deviceId", "?")[-12:]
            usage_ms = int(dev.get("currentUsageUsedMillis", 0))
            usage_min = round(usage_ms / 60000, 1)
            is_locked = dev.get("isLocked", False)
            policy = dev.get("activePolicy", "?")
            quota = None
            for key in ("inactiveCurrentUsageLimitEntry", "nextUsageLimitEntry"):
                entry = dev.get(key, {})
                if entry.get("usageQuotaMins"):
                    quota = entry["usageQuotaMins"]
                    break
            print(f"  [{dev_id}] used={usage_min}min locked={is_locked} policy={policy} quota={quota}min")
    else:
        print(f"  {json.dumps(data)[:400]}")


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)

    async with aiohttp.ClientSession() as session:
        # First: show current state
        await get_current_limits(session, cookies)

        print("\n\n=== Probing timeLimit:update payload formats ===")
        print(f"All tests use device={EMILIO_DEV[-12:]} minutes={TEST_MINUTES}")

        # --- Attempt 1: [device_id, minutes] ---
        await try_payload(
            session, cookies,
            "1: [device_id, minutes]",
            [EMILIO_DEV, TEST_MINUTES],
        )

        # --- Attempt 2: [device_id, None, minutes] ---
        await try_payload(
            session, cookies,
            "2: [device_id, None, minutes]",
            [EMILIO_DEV, None, TEST_MINUTES],
        )

        # --- Attempt 3: [[device_id, minutes]] (nested list) ---
        await try_payload(
            session, cookies,
            "3: [[device_id, minutes]]",
            [[EMILIO_DEV, TEST_MINUTES]],
        )

        # --- Attempt 4: [None, device_id, [[minutes]]] ---
        await try_payload(
            session, cookies,
            "4: [None, device_id, [[minutes]]]",
            [None, EMILIO_DEV, [[TEST_MINUTES]]],
        )

        # --- Attempt 5: [device_id, [[day_bitmask, minutes]]] ---
        # day_bitmask: 127 = all days (bits 0-6)
        await try_payload(
            session, cookies,
            "5: [device_id, [[127, minutes]]]",
            [EMILIO_DEV, [[127, TEST_MINUTES]]],
        )

        # --- Attempt 6: [None, [[device_id, minutes]]] ---
        await try_payload(
            session, cookies,
            "6: [None, [[device_id, minutes]]]",
            [None, [[EMILIO_DEV, TEST_MINUTES]]],
        )

        # --- Attempt 7: {"deviceId": device_id, "usageQuotaMins": minutes} (plain JSON) ---
        await try_payload(
            session, cookies,
            "7: plain JSON object {deviceId, usageQuotaMins}",
            {"deviceId": EMILIO_DEV, "usageQuotaMins": TEST_MINUTES},
        )

        # --- Attempt 8: [[[device_id, minutes]]] ---
        await try_payload(
            session, cookies,
            "8: [[[device_id, minutes]]]",
            [[[EMILIO_DEV, TEST_MINUTES]]],
        )

        # --- Attempt 9: [device_id, [[62, minutes], [1, minutes]]] ---
        # 62 = weekdays mask? (Mon-Fri = bits 1-5 = 0b0111110 = 62)
        await try_payload(
            session, cookies,
            "9: [device_id, [[62, minutes]]] (weekday mask)",
            [EMILIO_DEV, [[62, TEST_MINUTES]]],
        )

        # --- Attempt 10: GET the timeLimit resource first ---
        print("\n--- 10: GET timeLimit (read current) ---")
        url_get = f"{BASE}/people/{CHILD_ID}/timeLimit"
        h = make_headers(cookies)
        async with session.get(url_get, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
            status = r.status
            text = await r.text()
            print(f"  GET /timeLimit → {status}")
            if text:
                try:
                    print(f"  Body: {json.dumps(json.loads(text), indent=2)[:1000]}")
                except Exception:
                    print(f"  Body: {text[:500]}")

        # --- Attempt 11: GET timeLimits (plural) ---
        print("\n--- 11: GET timeLimits (plural) ---")
        url_get2 = f"{BASE}/people/{CHILD_ID}/timeLimits"
        async with session.get(url_get2, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
            status = r.status
            text = await r.text()
            print(f"  GET /timeLimits → {status}")
            if text:
                try:
                    print(f"  Body: {json.dumps(json.loads(text), indent=2)[:1000]}")
                except Exception:
                    print(f"  Body: {text[:500]}")

        # Final: show state again (should be unchanged since we used same value)
        await get_current_limits(session, cookies)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_timelimit_update.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
