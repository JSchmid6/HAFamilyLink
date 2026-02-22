"""Verify that timeLimit:update with [null, device_id, [[minutes]]] actually
sets the daily usage quota.

Strategy:
  1. Read current quota (expect 90)
  2. PUT [null, device_id, [[91]]]
  3. Read quota again (should be 91 if correct)
  4. PUT [null, device_id, [[90]]] → reset
  5. Confirm reset

If step 3 shows 91, we have the correct payload format for Tageslimit.

Usage:
    python scripts/verify_timelimit.py <path/to/familylink.cookies.json>
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


async def get_quota(session: aiohttp.ClientSession, cookies: dict) -> int | None:
    """Return the usageQuotaMins for Emilio's device from appliedTimeLimits."""
    url = (
        f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
        "?capabilities=TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
    )
    # Use application/json (NOT json+protobuf) to get clean JSON response
    h = {**make_headers(cookies), "Content-Type": "application/json"}
    async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
        text = await r.text()
    data = json.loads(text)
    if not isinstance(data, dict):
        print(f"  [get_quota] unexpected type: {type(data).__name__}")
        print(f"  raw: {text[:200]}")
        return None
    for dev in data.get("appliedTimeLimits", []):
        if dev.get("deviceId") == EMILIO_DEV:
            for key in ("inactiveCurrentUsageLimitEntry", "nextUsageLimitEntry"):
                entry = dev.get(key, {})
                q = entry.get("usageQuotaMins")
                if q:
                    return int(q)
    return None


async def put_time_limit(
    session: aiohttp.ClientSession,
    cookies: dict,
    minutes: int,
    payload_variant: str,
) -> int:
    """PUT timeLimit:update and return HTTP status."""
    url = f"{BASE}/people/{CHILD_ID}/timeLimit:update?$httpMethod=PUT"
    h = make_headers(cookies)

    # Known entry IDs for each day (from appliedTimeLimits JSPB response)
    # Decoded: CAEQAQ=day1, CAEQAg=day2, CAEQAw=day3, CAEQBA=day4,
    #          CAEQBQ=day5, CAEQBg=day6, CAEQBw=day7
    day_ids = ["CAEQAQ", "CAEQAg", "CAEQAw", "CAEQBA", "CAEQBQ", "CAEQBg", "CAEQBw"]

    if payload_variant == "A":
        # [null, device_id, [[minutes]]] – sets window_update (schedule), NOT quota
        payload = [None, EMILIO_DEV, [[minutes]]]
    elif payload_variant == "N":
        # new_entries is REPEATED: each entry = [[entry_id, day, type, quota]]
        # All 7 days in one usage_update item
        quota_entries = [[day_ids[i], i + 1, 2, minutes] for i in range(7)]
        usage_updates = [[None, quota_entries]]  # one usage_update, 7 new_entries
        payload = [None, EMILIO_DEV, [None, usage_updates]]
    elif payload_variant == "O":
        # 7 separate usage_update items, each with one new_entries entry
        usage_updates = [[None, [[day_ids[i], i + 1, 2, minutes]]] for i in range(7)]
        payload = [None, EMILIO_DEV, [None, usage_updates]]
    elif payload_variant == "P":
        # Maybe TimeUsageLimitEntry fields are: [quota, day, type, ...]  (quota first)
        quota_entries = [[minutes, i + 1, 2] for i in range(7)]
        usage_updates = [[None, quota_entries]]
        payload = [None, EMILIO_DEV, [None, usage_updates]]
    elif payload_variant == "Q":
        # Test with just ONE day (Saturday=7) and correct nesting
        payload = [None, EMILIO_DEV, [None, [[None, [["CAEQBw", 7, 2, minutes]]]]]]
    else:
        raise ValueError(f"Unknown variant: {payload_variant}")

    body = json.dumps(payload)
    print(f"  payload: {body}")
    async with session.post(url, headers=h, data=body, timeout=aiohttp.ClientTimeout(total=10)) as r:
        status = r.status
        text = await r.text()
        if text:
            try:
                parsed = json.loads(text)
                print(f"  status={status} response={json.dumps(parsed)[:300]}")
            except Exception:
                print(f"  status={status} body={text[:200]}")
        else:
            print(f"  status={status} (empty body)")
    return status


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)

    async with aiohttp.ClientSession() as session:
        # Step 1: Read current quota
        quota_before = await get_quota(session, cookies)
        print(f"\n[Before] Emilio quota = {quota_before} min")

        if quota_before is None:
            print("Could not read quota - appliedTimeLimits may be returning JSPB. Aborting.")
            return

        print(f"\n=== Test variant A: [null, device_id, [[91]]] ===")
        await put_time_limit(session, cookies, 91, "A")
        await asyncio.sleep(1)
        quota_after_a = await get_quota(session, cookies)
        print(f"[After A] Emilio quota = {quota_after_a} min")

        if quota_after_a == 91:
            print("  ✓ QUOTA CHANGED! Variant A is CORRECT.")
        else:
            print("  ✗ Quota unchanged with variant A")

        # Reset immediately
        print(f"\n=== Resetting to {quota_before} min ===")
        await put_time_limit(session, cookies, quota_before, "A")
        await asyncio.sleep(1)
        quota_reset = await get_quota(session, cookies)
        print(f"[Reset] Emilio quota = {quota_reset} min")
        if quota_reset == quota_before:
            print("  ✓ Reset successful")
        else:
            print(f"  ⚠ Reset may have failed! Current: {quota_reset}, expected: {quota_before}")

        # If A didn't work, try variants N-Q
        if quota_after_a != 91:
            for variant in ["N", "O", "P", "Q"]:
                print(f"\n=== Test variant {variant} ===")
                status = await put_time_limit(session, cookies, 91, variant)
                if status == 200:
                    await asyncio.sleep(1)
                    quota_check = await get_quota(session, cookies)
                    print(f"[After {variant}] Emilio quota = {quota_check} min")
                    if quota_check == 91:
                        print(f"  ✓ QUOTA CHANGED! Variant {variant} is CORRECT.")
                        print(f"\n=== Resetting to {quota_before} min ===")
                        await put_time_limit(session, cookies, quota_before, variant)
                        await asyncio.sleep(1)
                        print(f"[Reset] quota = {await get_quota(session, cookies)} min")
                        break
                    else:
                        print(f"  ✗ Quota unchanged with variant {variant}")
                else:
                    print(f"  → skipping quota check (status={status})")

        print("\nDone.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_timelimit.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
