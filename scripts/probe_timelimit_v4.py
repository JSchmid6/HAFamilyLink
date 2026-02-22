"""Targeted probing of timeLimit:update with specific theory-driven variants.

Based on analysis:
- Variants A-D get generic "invalid argument" → inner content wrong
- Variant G error reveals field2 of TimeLimitUpdate IS usage_updates
- GET /timeLimit returns group structure with [6,0] group_id and full entry detail
- Content-length 78 for browser success (variant C equivalent = 79 bytes, 1 byte off)

New theories to test:
T1: new_state = 1 instead of 2
T2: All 7 day entries at once (maybe partial update not supported)
T3: Include group_id [6,0] somewhere in the request
T4: UsageUpdate has entries at different field position
T5: No new_state field (entries directly)
T6: created_ts as integer not string
T7: Different outer field count (4 fields in top-level array)

Usage:
    python scripts/probe_timelimit_v4.py <path/to/familylink.cookies.json>
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
EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def load_cookies(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {c["name"]: c["value"] for c in data}


def sapisidhash(sapisid: str) -> str:
    ts = str(int(time.time() * 1000))
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"{ts}_{digest}"


def make_headers(cookies: dict) -> dict:
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    auth = sapisidhash(sapisid)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
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


async def get_time_limit_raw(session: aiohttp.ClientSession, cookies: dict) -> tuple[list, list]:
    """GET /timeLimit and return (raw_data, entries_list)."""
    url = f"{BASE}/people/{CHILD_ID}/timeLimit"
    async with session.get(url, headers=make_headers(cookies)) as r:
        text = await r.text()
    if r.status != 200:
        print(f"  [GET /timeLimit] HTTP {r.status}: {text[:200]}")
        return [], []
    data = json.loads(text)
    try:
        entries = data[1][1][0][2]
        return data, entries
    except (IndexError, TypeError):
        print(f"  [GET /timeLimit] Could not parse entries. Raw: {text[:300]}")
        return data, []


async def put_update(
    session: aiohttp.ClientSession,
    cookies: dict,
    label: str,
    payload: list,
) -> tuple[int, str]:
    payload_str = json.dumps(payload, separators=(",", ":"))
    payload_bytes = payload_str.encode("utf-8")
    print(f"\n{'─'*64}")
    print(f"  [{label}] {len(payload_bytes)} bytes")
    print(f"  Payload: {payload_str}")
    url = f"{BASE}/people/{CHILD_ID}/timeLimit:update?$httpMethod=PUT"
    try:
        async with session.post(
            url, data=payload_bytes, headers=make_headers(cookies),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            text = await r.text()
        print(f"  → HTTP {r.status}: {text[:300]}")
        return r.status, text
    except Exception as ex:
        print(f"  → ERROR: {ex}")
        return 0, str(ex)


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)

    async with aiohttp.ClientSession() as session:
        print("=" * 64)
        print("Step 1: Read current timeLimit state")
        print("=" * 64)
        raw_data, entries = await get_time_limit_raw(session, cookies)

        if not entries:
            print("FATAL: Cannot read entries.")
            return

        print(f"  Entries ({len(entries)}):")
        for e in entries:
            print(f"    {e[0]} day={e[1]} type={e[2]} quota={e[3]} min  created={e[4] if len(e)>4 else '?'}  modified={e[5] if len(e)>5 else '?'}")

        monday = next((e for e in entries if e[1] == 1), None)
        if not monday:
            print("FATAL: Monday not found.")
            return

        entry_id = monday[0]
        day_num = monday[1]
        etype = monday[2]
        quota_orig = monday[3]
        created_ts = monday[4] if len(monday) > 4 else None
        modified_ts = monday[5] if len(monday) > 5 else None

        test_q = (quota_orig + 5) if quota_orig < 475 else (quota_orig - 5)
        reset_q = quota_orig
        print(f"\n  Monday: id={entry_id}, quota={quota_orig} → test with {test_q}")

        # Build all 7 entries with test quota applied to Monday only
        entries_all_test = []
        for e in entries:
            q = test_q if e[1] == 1 else e[3]
            entries_all_test.append([e[0], e[1], e[2], q])

        # Build all 7 entries with FULL fields (including timestamps)
        entries_all_full = []
        for e in entries:
            q = test_q if e[1] == 1 else e[3]
            full_e = [e[0], e[1], e[2], q]
            if len(e) > 4:
                full_e.append(e[4])
            if len(e) > 5:
                full_e.append(e[5])
            entries_all_full.append(full_e)

        # Single entry variants
        entry_s = [entry_id, day_num, etype, test_q]  # short
        entry_c = [entry_id, day_num, etype, test_q, created_ts]  # + created
        entry_f = [entry_id, day_num, etype, test_q, created_ts, modified_ts]  # full

        child = CHILD_ID

        # T1: new_state = 1 (not 2)
        # T2: All 7 entries, state=2
        # T3: All 7 entries, state=1
        # T4: UsageUpdate with null at field2, entries at field3
        # T5: No state (entries directly in UsageUpdate without state field)
        # T6: created_ts as integer, not string
        # T7: 4 top-level fields in request
        # T8: [6, 0] group_id variant

        created_int = int(created_ts) if created_ts else None
        modified_int = int(modified_ts) if modified_ts else None
        entry_int_ts = [entry_id, day_num, etype, test_q, created_int]

        variants: list[tuple[str, list]] = [
            # ── State value variations ─────────────────────────────────────
            ("T1-state1-short",  [None, child, [None, [[1, [entry_s]]]]]),
            ("T1-state3-short",  [None, child, [None, [[3, [entry_s]]]]]),
            ("T1-state0-short",  [None, child, [None, [[0, [entry_s]]]]]),

            # ── All 7 entries ──────────────────────────────────────────────
            ("T2-all7-state2-short", [None, child, [None, [[2, entries_all_test]]]]),
            ("T3-all7-state1-short", [None, child, [None, [[1, entries_all_test]]]]),
            ("T3-all7-state2-full",  [None, child, [None, [[2, entries_all_full]]]]),

            # ── UsageUpdate inner field position variations ────────────────
            # field1=null, field2=null, field3=entries (state omitted?)
            ("T4-no-state",     [None, child, [None, [[None, None, [entry_s]]]]]),
            # field1=entries directly (no state)
            ("T5-entries-only", [None, child, [None, [[[entry_s]]]]]),

            # ── Created timestamp as integer ───────────────────────────────
            ("T6-int-ts",       [None, child, [None, [[2, [entry_int_ts]]]]]),

            # ── More top-level fields ──────────────────────────────────────
            ("T7-4fields",      [None, child, None, [None, [[2, [entry_s]]]]]),
            ("T8-4fields-v2",   [None, child, [None, [[2, [entry_s]]]], None]),

            # ── Group ID theories ─────────────────────────────────────────
            # The GET response shows [2,[6,0],entries,...] - maybe [6,0] is group_id
            # Theory: UsageUpdate has [state, group_flags, entries]
            ("T9-group60",     [None, child, [None, [[2, [6, 0], [entry_s]]]]]),
            ("T9-group60-v2",  [None, child, [None, [[2, [6, 0], [entry_f]]]]]),
            ("T9-group60-all", [None, child, [None, [[2, [6, 0], entries_all_test]]]]),

            # ── Wrap entries in extra list layer ──────────────────────────
            ("T10-extra-wrap",  [None, child, [None, [[2, [[entry_s]]]]]]),

            # ── Just the update part (no null, no child_id in body) ───────
            ("T11-no-outer",    [[None, [[2, [entry_s]]]]]),
            ("T12-update-only", [None, [[2, [entry_s]]]]),
        ]

        print(f"\n{'='*64}")
        print(f"Step 2: Probe {len(variants)} variants")
        print(f"{'='*64}")

        success_list = []

        for label, payload in variants:
            status, body = await put_update(session, cookies, label, payload)
            if status == 200:
                success_list.append((label, payload, body))
                print(f"\n  ✓ HTTP 200 on {label}! Verifying...")
                await asyncio.sleep(1)
                _, entries_new = await get_time_limit_raw(session, cookies)
                new_q = next((e[3] for e in entries_new if e[1] == 1), None)
                if new_q == test_q:
                    print(f"  ✓✓ CONFIRMED: Monday quota {quota_orig} → {test_q}")
                    print(f"  ✓✓ WORKING PAYLOAD: {json.dumps(payload, separators=(',',':'))}")
                    # Reset
                    reset_payload = json.loads(
                        json.dumps(payload, separators=(",",":"))
                        .replace(f",{test_q},", f",{reset_q},")
                        .replace(f",{test_q}]", f",{reset_q}]")
                    )
                    print(f"\n  Resetting to {reset_q}...")
                    await put_update(session, cookies, "RESET", reset_payload)
                    break
                else:
                    print(f"  HTTP 200 but quota unchanged (still {new_q})")
            await asyncio.sleep(0.4)

        print(f"\n{'='*64}")
        print("Summary")
        print(f"{'='*64}")
        if success_list:
            for lbl, pl, body in success_list:
                print(f"✓ {lbl}: {json.dumps(pl, separators=(',',':'))}")
        else:
            print("✗ No variant succeeded with HTTP 200.")

        # Show final state
        print("\nFinal timeLimit state:")
        _, final_entries = await get_time_limit_raw(session, cookies)
        for e in final_entries:
            day_name = DAY_NAMES.get(e[1], f"day{e[1]}")
            print(f"  {e[0]} {day_name}: {e[3]} min")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_timelimit_v4.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
