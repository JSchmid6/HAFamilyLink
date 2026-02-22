"""Probe the timeLimit:update endpoint with corrected URL construction.

Two new approaches based on DevTools header analysis:
  1. BROWSER MODE: POST with content-type=text/plain + all API headers embedded
     in $httpHeaders URL query parameter (exactly as the browser does it)
  2. DIRECT MODE: POST with content-type=application/json+protobuf as direct headers
     (as our existing working endpoints do)

Also tests additional extension header x-goog-ext-198889211-bin from the URL.

First gets current timeLimit schedule to build correct entry objects.

Usage:
    python scripts/probe_timelimit_v3.py <path/to/familylink.cookies.json>
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from urllib.parse import quote

import aiohttp

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
CHILD_ID = "112452138243419815198"
EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

# ── Day name mapping ────────────────────────────────────────────────────────
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def load_cookies(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {c["name"]: c["value"] for c in data}


def sapisidhash(sapisid: str) -> str:
    ts = str(int(time.time() * 1000))
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"{ts}_{digest}"


def make_auth(cookies: dict) -> tuple[str, str]:
    """Return (sapisidhash, cookie_string)."""
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    auth = sapisidhash(sapisid)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return auth, cookie_str


# ── GET timeLimit to read current schedule ───────────────────────────────────

async def get_time_limit(session: aiohttp.ClientSession, cookies: dict) -> list:
    """GET /timeLimit and return the usage-limit entries list.

    Returns list of [entry_id, day_num, type, quota_mins, created_ts, modified_ts].
    """
    url = f"{BASE}/people/{CHILD_ID}/timeLimit"
    auth, cookie_str = make_auth(cookies)
    h = {
        "Authorization": f"SAPISIDHASH {auth}",
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json+protobuf",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "Cookie": cookie_str,
        "x-goog-ext-223261916-bin": EXT_223,
        "x-goog-ext-202964622-bin": EXT_202,
    }
    async with session.get(url, headers=h) as r:
        text = await r.text()
    print(f"  [GET /timeLimit] HTTP {r.status}")
    if r.status != 200:
        print(f"  body: {text[:300]}")
        return []
    data = json.loads(text)
    # Response structure: [[null,"ts"], [[2, window_sched, ts, ts, 1], [[2,[6,0], entries, ts, ts]]], ...]
    # entries are at data[1][1][0][2] typically — let's search for the list of entries
    # Each entry: [entry_id (str), day (int), type (int), quota_mins (int), created_ts (str), modified_ts (str)]
    try:
        entries = data[1][1][0][2]
        print(f"  Found {len(entries)} day entries:")
        for e in entries:
            day_name = DAY_NAMES.get(e[1], f"day{e[1]}")
            print(f"    {e[0]} = {day_name} ({e[1]}), type={e[2]}, quota={e[3]} min")
        return entries
    except (IndexError, TypeError, KeyError) as ex:
        print(f"  Could not parse entries: {ex}")
        print(f"  raw: {text[:500]}")
        return []


async def get_quota_for_day(session: aiohttp.ClientSession, cookies: dict, day_num: int) -> int | None:
    """Read quota minutes for a specific day from GET /timeLimit."""
    entries = await get_time_limit(session, cookies)
    for e in entries:
        if e[1] == day_num:
            return e[3]
    return None


# ── PUT timeLimit:update ──────────────────────────────────────────────────────

async def try_update(
    session: aiohttp.ClientSession,
    cookies: dict,
    label: str,
    payload_list: list,
    *,
    browser_mode: bool = False,
) -> tuple[int, str]:
    """POST to timeLimit:update?$httpMethod=PUT.

    Args:
        browser_mode: If True, embeds API headers in $httpHeaders URL param
                      and uses text/plain content-type (browser emulation).
                      If False, sends API headers directly (Python mode).
    """
    auth, cookie_str = make_auth(cookies)
    payload_str = json.dumps(payload_list, separators=(",", ":"))
    payload_bytes = payload_str.encode("utf-8")
    print(f"\n{'─'*60}")
    print(f"  Variant {label} ({'browser' if browser_mode else 'direct'})")
    print(f"  Payload ({len(payload_bytes)} bytes): {payload_str}")

    if browser_mode:
        # Build $httpHeaders value: CRLF-separated "Key:Value" lines, URL-encoded
        http_headers_value = (
            f"Content-Type:application/json+protobuf\r\n"
            f"X-Goog-AuthUser:0\r\n"
            f"Authorization:SAPISIDHASH {auth}\r\n"
            f"X-Goog-Api-Key:{API_KEY}\r\n"
            f"x-goog-ext-223261916-bin:{EXT_223}\r\n"
            f"x-goog-ext-202964622-bin:{EXT_202}\r\n"
        )
        encoded_headers = quote(http_headers_value, safe="")
        url = (
            f"{BASE}/people/{CHILD_ID}/timeLimit:update"
            f"?%24httpHeaders={encoded_headers}&%24httpMethod=PUT"
        )
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": ORIGIN,
            "Referer": f"{ORIGIN}/",
            "Cookie": cookie_str,
            "x-browser-channel": "stable",
        }
    else:
        # Direct mode: API headers as actual HTTP headers
        url = f"{BASE}/people/{CHILD_ID}/timeLimit:update?$httpMethod=PUT"
        headers = {
            "Content-Type": "application/json+protobuf",
            "Authorization": f"SAPISIDHASH {auth}",
            "X-Goog-AuthUser": "0",
            "X-Goog-Api-Key": API_KEY,
            "Origin": ORIGIN,
            "Referer": f"{ORIGIN}/",
            "Cookie": cookie_str,
            "x-goog-ext-223261916-bin": EXT_223,
            "x-goog-ext-202964622-bin": EXT_202,
        }

    try:
        async with session.post(
            url, data=payload_bytes, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as r:
            text = await r.text()
        print(f"  → HTTP {r.status}: {text[:200]}")
        return r.status, text
    except Exception as ex:
        print(f"  → ERROR: {ex}")
        return 0, str(ex)


# ── Main probe ────────────────────────────────────────────────────────────────

async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)

    async with aiohttp.ClientSession() as session:
        print("=" * 60)
        print("Step 1: Read current timeLimit schedule")
        print("=" * 60)
        entries = await get_time_limit(session, cookies)
        if not entries:
            print("FATAL: Could not read entries. Cannot continue.")
            return

        # Find Monday (day 1) entry
        monday = next((e for e in entries if e[1] == 1), None)
        if not monday:
            print("FATAL: Monday entry not found.")
            return

        entry_id = monday[0]   # e.g. "CAEQAQ"
        day_num = monday[1]    # 1
        etype = monday[2]      # 2
        quota_orig = monday[3] # current quota
        created_ts = monday[4] if len(monday) > 4 else None
        modified_ts = monday[5] if len(monday) > 5 else None

        # Pick a test quota value different from current
        test_quota = (quota_orig + 5) if quota_orig < 475 else (quota_orig - 5)

        print(f"\nMonday entry: id={entry_id}, quota_orig={quota_orig}, test_quota={test_quota}")
        print(f"  created_ts={created_ts}, modified_ts={modified_ts}")

        # ── Build entry variants ──────────────────────────────────────────────
        # Short entry (no timestamps)
        entry_short = [entry_id, day_num, etype, test_quota]
        # Entry with created_ts only
        entry_with_created = [entry_id, day_num, etype, test_quota, created_ts]
        # Full entry (with both timestamps)
        entry_full = [entry_id, day_num, etype, test_quota, created_ts, modified_ts]

        print(f"\nEntry variants:")
        for name, e in [("short", entry_short), ("with_created", entry_with_created), ("full", entry_full)]:
            s = json.dumps(e, separators=(",", ":"))
            print(f"  {name} ({len(s)} bytes): {s}")

        print("\n" + "=" * 60)
        print("Step 2: Try PUT variants")
        print("=" * 60)

        # ── Variant matrix ───────────────────────────────────────────────────
        # Structure hypothesis from proto schema:
        # TimeLimitUpdateRequest = [null, child_id, TimeLimitUpdate]
        # TimeLimitUpdate.field2 = usage_updates[] = [[UsageUpdate]]
        # UsageUpdate = [new_state, new_entries[]]
        # new_state: 2=ACTIVE, null=omit
        # new_entries: list of TimeUsageLimitEntry

        child = CHILD_ID

        variants = [
            # (label, payload, browser_mode)
            # --- DIRECT MODE variants ---
            # A: [null, child, [null, [[2, [entry]]]]]   -- state=2, short entry
            ("A-direct", [None, child, [None, [[2, [entry_short]]]]], False),
            # B: same but state=null
            ("B-direct", [None, child, [None, [[None, [entry_short]]]]], False),
            # C: [null, child, [null, [[2, [entry_with_created]]]]]
            ("C-direct", [None, child, [None, [[2, [entry_with_created]]]]], False),
            # D: [null, child, [null, [[2, [entry_full]]]]]
            ("D-direct", [None, child, [None, [[2, [entry_full]]]]], False),
            # E: [null, child, [[[[entry_short]]]]]  -- skip nested state layer
            ("E-direct", [None, child, [[[[entry_short]]]]], False),
            # F: [null, child, [[[entry_short]]]]  -- even flatter
            ("F-direct", [None, child, [[[entry_short]]]], False),
            # G: [null, child, [[2, [entry_short]]]]  -- usage_updates at top level
            ("G-direct", [None, child, [[2, [entry_short]]]], False),

            # --- BROWSER MODE variants (same payloads but text/plain + $httpHeaders) ---
            ("A-browser", [None, child, [None, [[2, [entry_short]]]]], True),
            ("C-browser", [None, child, [None, [[2, [entry_with_created]]]]], True),
            ("D-browser", [None, child, [None, [[2, [entry_full]]]]], True),
            ("G-browser", [None, child, [[2, [entry_short]]]], True),
        ]

        success_variants = []

        for label, payload, browser_mode in variants:
            status, body = await try_update(session, cookies, label, payload, browser_mode=browser_mode)
            if status == 200:
                success_variants.append((label, payload, browser_mode, body))
                # Verify the change
                print(f"\n  ✓ HTTP 200! Verifying quota change...")
                await asyncio.sleep(1)
                new_quota = await get_quota_for_day_timelimit(session, cookies, day_num, entries)
                print(f"  Original quota: {quota_orig} → Current quota (from /timeLimit): {new_quota}")
                if new_quota == test_quota:
                    print(f"  ✓✓ CONFIRMED: Quota changed from {quota_orig} to {test_quota}!")
                    print(f"  ✓✓ WORKING PAYLOAD FORMAT: {json.dumps(payload)}")
                    # Reset immediately
                    print(f"\n  Resetting to original {quota_orig}...")
                    reset_payload = build_payload_from(payload, entry_id, day_num, etype, quota_orig, created_ts, test_quota)
                    await try_update(session, cookies, "RESET", reset_payload, browser_mode=browser_mode)
                    break
                else:
                    print(f"  ✗ Quota unchanged – HTTP 200 response but no effect")
            await asyncio.sleep(0.5)

        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        if success_variants:
            print(f"✓ {len(success_variants)} variant(s) got HTTP 200")
            for lbl, pl, bm, body in success_variants:
                print(f"  {lbl}: {json.dumps(pl, separators=(',',':'))}")
        else:
            print("✗ No variant succeeded.")


def build_payload_from(
    template: list,
    entry_id: str,
    day_num: int,
    etype: int,
    quota: int,
    created_ts: str | None,
    old_test_quota: int,
) -> list:
    """Rebuild the same payload structure but with the original quota."""
    import copy
    p = copy.deepcopy(template)
    s = json.dumps(p)
    s = s.replace(f",{old_test_quota},", f",{quota},")
    s = s.replace(f",{old_test_quota}]", f",{quota}]")
    return json.loads(s)


async def get_quota_for_day_timelimit(
    session: aiohttp.ClientSession,
    cookies: dict,
    day_num: int,
    orig_entries: list,
) -> int | None:
    """Re-read /timeLimit and return quota for a specific day."""
    entries = await get_time_limit(session, cookies)
    for e in entries:
        if e[1] == day_num:
            return e[3]
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_timelimit_v3.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
