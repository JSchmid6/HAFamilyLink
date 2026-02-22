"""
Test: GET timeLimit -> modify one day's quota -> PUT back -> verify -> reset.
Usage: .\.venv\Scripts\python.exe scripts\test_set_daily_limit.py <cookies.json>
"""

import asyncio
import json
import sys
import time
from pathlib import Path
import aiohttp
import hashlib

CHILD_ID = "112452138243419815198"
API_BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
GOOG_EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
GOOG_EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

DAY_NAMES = {1: "monday", 2: "tuesday", 3: "wednesday", 4: "thursday",
             5: "friday", 6: "saturday", 7: "sunday"}


def build_auth(sapisid: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def load_cookies(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    return {c["name"]: c["value"] for c in data}


def make_headers(cookies: dict, sapisid: str, content_type: str) -> dict:
    return {
        "Authorization": build_auth(sapisid),
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Origin": ORIGIN,
        "Content-Type": content_type,
        "x-goog-ext-223261916-bin": GOOG_EXT_223,
        "x-goog-ext-202964622-bin": GOOG_EXT_202,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }


async def get_time_limit_jspb(session: aiohttp.ClientSession, headers: dict) -> list:
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit"
    async with session.get(url, headers=headers) as r:
        text = await r.text()
        if r.status != 200:
            raise RuntimeError(f"GET timeLimit failed: {r.status} - {text[:200]}")
        return json.loads(text)


def find_quota_entry(data: list, target_day: int) -> tuple:
    """data[1][1][0][2] = list of [entry_id, day, type, quota_mins, created_ts, modified_ts]"""
    quota_group = data[1][1][0]
    quotas = quota_group[2]
    for i, entry in enumerate(quotas):
        if entry[1] == target_day:
            return quotas, i
    raise KeyError(f"Day {target_day} not found in quota list")


def build_put_body(data: list, target_day: int, new_quota: int) -> str:
    """
    Build the minimal PUT body confirmed from browser DevTools Payload tab:

      [null, CHILD_ID, [null, [[2, null, null, [[entry_id, new_quota]]]]], null, [1]]

    Only entry_id + new quota_mins are sent.
    Per-entry field: [entry_id_str, quota_mins_int]
    """
    quotas, idx = find_quota_entry(data, target_day)
    old_quota = quotas[idx][3]
    entry_id = quotas[idx][0]

    body = [
        None,
        CHILD_ID,
        [None, [[2, None, None, [[entry_id, new_quota]]]]],
        None,
        [1],
    ]

    print(f"   Day {DAY_NAMES[target_day]} ({target_day}): {old_quota} -> {new_quota} min  [entry_id={entry_id}]")
    return json.dumps(body, separators=(",", ":"))


async def put_time_limit(session: aiohttp.ClientSession, headers: dict,
                         body: str, label: str) -> None:
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
    params = {"$httpMethod": "PUT"}
    print(f"   Sending body ({len(body)} chars): {body}")
    async with session.post(url, headers=headers, params=params, data=body) as r:
        resp = await r.text()
        print(f"   PUT [{label}] -> Status: {r.status}  Response: {resp[:400]}")


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")

    async with aiohttp.ClientSession() as session:

        # Step 1: GET current state
        print("=" * 60)
        print("1. GET current timeLimit (JSPB)")
        h = make_headers(cookies, sapisid, "application/json+protobuf")
        data = await get_time_limit_jspb(session, h)
        quotas, _ = find_quota_entry(data, 1)
        print("   Current quotas per day:")
        for entry in quotas:
            day_name = DAY_NAMES.get(entry[1], f"day{entry[1]}")
            print(f"     {day_name:12s} ({entry[1]}): {entry[3]:3d} min  [id={entry[0]}]")
        current_monday = quotas[next(i for i, e in enumerate(quotas) if e[1] == 1)][3]

        # Step 2: SET Monday +1
        print()
        print("=" * 60)
        print(f"2. SET Monday: {current_monday} -> {current_monday + 1} min")
        body_up = build_put_body(data, target_day=1, new_quota=current_monday + 1)
        await put_time_limit(session, make_headers(cookies, sapisid, "application/json+protobuf"), body_up, "change")

        # Step 3: Verify
        print()
        print("=" * 60)
        print("3. Verify: GET again")
        await asyncio.sleep(1)
        data2 = await get_time_limit_jspb(session, make_headers(cookies, sapisid, "application/json+protobuf"))
        q2, idx2 = find_quota_entry(data2, 1)
        new_val = q2[idx2][3]
        ok = new_val == current_monday + 1
        print(f"   Monday quota after PUT: {new_val} min  ({'OK CHANGED' if ok else 'NO CHANGE'})")

        # Step 4: Reset
        print()
        print("=" * 60)
        print(f"4. RESET Monday back to {current_monday} min")
        body_reset = build_put_body(data2, target_day=1, new_quota=current_monday)
        await put_time_limit(session, make_headers(cookies, sapisid, "application/json+protobuf"), body_reset, "reset")

        # Step 5: Final verify
        print()
        print("=" * 60)
        print("5. Final verify")
        await asyncio.sleep(1)
        data3 = await get_time_limit_jspb(session, make_headers(cookies, sapisid, "application/json+protobuf"))
        q3, idx3 = find_quota_entry(data3, 1)
        final_val = q3[idx3][3]
        print(f"   Monday quota after reset: {final_val} min  ({'RESET OK' if final_val == current_monday else 'RESET FAILED'})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_set_daily_limit.py <path-to-cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
