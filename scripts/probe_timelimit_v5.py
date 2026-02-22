"""Targeted probe v5: Focus on entry structure variations.

Key insight from v4:
- T4: UsageUpdate=[null,null,entries] → HTTP 200 but changes WINDOW schedule, not quota
- T9: [6,0] at field2 → new_entries[0]=6, new_entries[1]=0 → field2=new_entries confirmed
- A-D: [state, [entries]] → items at new_entries → 400 "invalid argument"

Missing piece: why is [state, [[id,day,type,quota]]] invalid?

Possible reasons:
1. Entry structure wrong: maybe no type field, or different field order
2. ID "CAEQAQ" needs to be absent (null) or different
3. Timestamps are REQUIRED in new_entries
4. new_state has a constraint (must match a specific valid value for this operation)
5. UsageUpdate needs additional fields beyond [state, entries]

This script tests entry format variations to narrow it down.

Usage:
    python scripts/probe_timelimit_v5.py <path/to/familylink.cookies.json>
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


def make_headers(cookies: dict) -> dict:
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    ts = str(int(time.time() * 1000))
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Authorization": f"SAPISIDHASH {ts}_{digest}",
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json+protobuf",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "Cookie": cookie_str,
        "x-goog-ext-223261916-bin": EXT_223,
        "x-goog-ext-202964622-bin": EXT_202,
    }


async def get_timelimit_entries(session: aiohttp.ClientSession, cookies: dict) -> list:
    url = f"{BASE}/people/{CHILD_ID}/timeLimit"
    async with session.get(url, headers=make_headers(cookies)) as r:
        text = await r.text()
    if r.status != 200:
        return []
    data = json.loads(text)
    try:
        return data[1][1][0][2]
    except (IndexError, TypeError):
        return []


async def put_update(
    session: aiohttp.ClientSession,
    cookies: dict,
    label: str,
    payload: list,
) -> tuple[int, str]:
    p_str = json.dumps(payload, separators=(",", ":"))
    p_bytes = p_str.encode()
    print(f"\n{'─'*64}")
    print(f"  [{label}] {len(p_bytes)} bytes")
    print(f"  Payload: {p_str}")
    url = f"{BASE}/people/{CHILD_ID}/timeLimit:update?$httpMethod=PUT"
    async with session.post(
        url, data=p_bytes, headers=make_headers(cookies),
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        text = await r.text()
    print(f"  → HTTP {r.status}: {text[:400]}")
    return r.status, text


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)

    async with aiohttp.ClientSession() as session:
        print("=" * 64)
        print("Reading current entries…")
        print("=" * 64)
        entries = await get_timelimit_entries(session, cookies)
        for e in entries:
            print(f"  {e[0]} day={e[1]} quota={e[3]}")

        monday = next((e for e in entries if e[1] == 1), None)
        if not monday:
            print("FATAL: no Monday entry")
            return

        eid, day, etype, q_orig = monday[0], monday[1], monday[2], monday[3]
        ts_c = monday[4] if len(monday) > 4 else None
        ts_m = monday[5] if len(monday) > 5 else None
        q = (q_orig + 5) if q_orig < 475 else (q_orig - 5)
        child = CHILD_ID

        print(f"\n  Monday: id={eid}, day={day}, type={etype}, quota={q_orig}→test={q}")
        print(f"  created_ts={ts_c}  modified_ts={ts_m}")

        # ── Entry structure variants ────────────────────────────────────────
        # Current best knowledge: TimeUsageLimitEntry = [id, day, type, quota, ts_c, ts_m]
        # But maybe the structure is different.
        # Let's systematically strip/swap fields.

        # Short form confirmed from GET response:
        e_short        = [eid, day, etype, q]                        # [id,day,type,quota]
        e_no_type      = [eid, day, q]                               # [id,day,quota] – skip type
        e_id_quota     = [eid, q]                                    # [id,quota] only
        e_null_id      = [None, day, etype, q]                       # null id
        e_null_id_c    = [None, day, etype, q, ts_c]                 # null id + created_ts
        e_no_id        = [day, etype, q]                             # no id at all
        e_short_reordr = [eid, etype, day, q]                        # swap day/type
        e_with_c_only  = [eid, day, etype, q, ts_c]                  # + created_ts
        e_full         = [eid, day, etype, q, ts_c, ts_m]            # all 6 fields

        # State values to check
        STATE_OPTS = [2, 1, None]

        variants: list[tuple[str, list]] = []
        for state in STATE_OPTS:
            state_str = str(state)
            for entry, e_name in [
                (e_short,       "short"),
                (e_no_type,     "no_type"),
                (e_id_quota,    "id_quota"),
                (e_null_id,     "null_id"),
                (e_no_id,       "no_id"),
                (e_with_c_only, "with_c"),
                (e_full,        "full"),
            ]:
                label = f"state{state_str}-{e_name}"
                payload = [None, child, [None, [[state, [entry]]]]]
                variants.append((label, payload))

        # Extra: try UsageUpdate with no state wrapper (just entries list directly)
        variants.append(("no-state-wrap-short", [None, child, [None, [[e_short]]]]))
        variants.append(("no-state-wrap-full",  [None, child, [None, [[e_full]]]]))

        # Extra: T4-success structure but with correct quota field
        # T4 was [null,null,entries] → 200 but changed window
        # What if entries need different structure for usage vs window?
        # The window "CAEQAQ" entry had [0,0] (TimeOfDay) at field3 not field3=type
        # Usage entry needs [id, day, type, quota]
        # Maybe for USAGE update, put entry at the RIGHT field position
        # i.e. usage entries can't go to field3 because that is for window entries
        variants.append(("T4-full-entry",   [None, child, [None, [[None, None, [e_full]]]]]))

        print(f"\n{'='*64}")
        print(f"Testing {len(variants)} variants...")
        print(f"{'='*64}")

        success = []
        for label, payload in variants:
            status, body = await put_update(session, cookies, label, payload)
            if status == 200:
                success.append((label, payload, body))
                # If it's just [[1]], it probably changed the quota
                if body.strip() == "[[1]]":
                    print(f"\n  ✓✓ Response [[1]] → QUOTA CHANGE CONFIRMED!")
                    # Verify
                    await asyncio.sleep(1)
                    fresh = await get_timelimit_entries(session, cookies)
                    new_q = next((e[3] for e in fresh if e[1] == 1), None)
                    print(f"  Quota: {q_orig} → {new_q} (expected {q})")
                    if new_q == q:
                        print(f"  ✓✓✓ WORKING PAYLOAD: {json.dumps(payload, separators=(',',':'))}")
                        # Reset
                        reset = json.loads(json.dumps(payload, separators=(",",":"))
                                          .replace(f",{q},", f",{q_orig},")
                                          .replace(f",{q}]", f",{q_orig}]"))
                        print(f"  Resetting to {q_orig}...")
                        await put_update(session, cookies, "RESET", reset)
                        break
            await asyncio.sleep(0.4)

        print(f"\n{'='*64}")
        print("Summary")
        print(f"{'='*64}")
        if success:
            for lbl, pl, body in success:
                r = "[[1]] ← QUOTA" if body.strip() == "[[1]]" else "complex response"
                print(f"  ✓ {lbl}: response={r}")
        else:
            print("✗ No HTTP 200 results.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_timelimit_v5.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
