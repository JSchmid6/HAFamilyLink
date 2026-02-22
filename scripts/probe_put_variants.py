"""
Brute-force test: try minimal PUT body variants for timeLimit:update.
Usage: .\.venv\Scripts\python.exe scripts\probe_put_variants.py <cookies.json>
"""

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
import aiohttp

CHILD_ID = "112452138243419815198"
API_BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
GOOG_EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
GOOG_EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

# From GET /timeLimit (stable IDs)
SUPERVISION_MODE_ID = "51a4ee09-ba93-42f6-8eaa-d04433152f7f"
SCHEDULE_CREATED_TS = "1704391266952"
SCHEDULE_MODIFIED_TS = "1716144515214"
QUOTAS_CREATED_TS = "1691759143732"
QUOTAS_MODIFIED_TS = "1771690094053"  # last change by app
SUPERVISION_TS_SEC = "1704391266"
SUPERVISION_TS_NS = 952246000

# Current quotas (from GET)
QUOTAS = [
    ["CAEQAQ", 1, 2, 40, QUOTAS_CREATED_TS, QUOTAS_MODIFIED_TS],
    ["CAEQAg", 2, 2, 30, QUOTAS_CREATED_TS, "1758601179250"],
    ["CAEQAw", 3, 2, 30, QUOTAS_CREATED_TS, "1716920233606"],
    ["CAEQBA", 4, 2, 30, QUOTAS_CREATED_TS, "1716920233606"],
    ["CAEQBQ", 5, 2, 30, QUOTAS_CREATED_TS, "1716920233606"],
    ["CAEQBg", 6, 2, 90, "1691853135824",   "1716920233606"],
    ["CAEQBw", 7, 2, 90, "1691853135824",   "1716920233606"],
]

# Schedule windows – same as captured from DevTools
SCHEDULE_WINDOWS = [
    ["CAEQAQ", 1, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQAg", 2, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQAw", 3, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBA", 4, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBQ", 5, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBg", 6, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBw", 7, 2, [0, 0], [3, 0],
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
]

# Same, but startsAt/endsAt as null (proto3 default = omit)
SCHEDULE_WINDOWS_NULL_TIMES = [
    ["CAEQAQ", 1, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQAg", 2, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQAw", 3, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBA", 4, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBQ", 5, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBg", 6, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
    ["CAEQBw", 7, 2, None, None,
     SCHEDULE_MODIFIED_TS, SCHEDULE_MODIFIED_TS, SUPERVISION_MODE_ID],
]


def ts() -> str:
    return str(int(time.time() * 1000))


def build_headers(cookies: dict, sapisid: str) -> dict:
    now = int(time.time() * 1000)
    digest = hashlib.sha1(f"{now} {sapisid} {ORIGIN}".encode()).hexdigest()
    return {
        "Authorization": f"SAPISIDHASH {now}_{digest}",
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Origin": ORIGIN,
        "Content-Type": "application/json+protobuf",
        "x-goog-ext-223261916-bin": GOOG_EXT_223,
        "x-goog-ext-202964622-bin": GOOG_EXT_202,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }


async def probe(session: aiohttp.ClientSession, headers: dict,
                label: str, body_obj) -> bool:
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
    body_str = json.dumps(body_obj)
    async with session.post(url, headers=headers,
                            params={"$httpMethod": "PUT"},
                            data=body_str) as r:
        resp = await r.text()
        ok = r.status == 200
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {label}: HTTP {r.status}")
        if not ok:
            print(f"       {resp[:300]}")
        return ok


async def main(cookie_path: str) -> None:
    cookies = json.loads(Path(cookie_path).read_text())
    cookies = {c["name"]: c["value"] for c in cookies}
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")

    now_q = ts()
    quot_no_change = [list(q) for q in QUOTAS]
    quot_40 = [list(q) for q in QUOTAS]      # Monday = 40 (no-op, safe test)

    supervision = [[SUPERVISION_MODE_ID, 1, 2,
                    [SUPERVISION_TS_SEC, SUPERVISION_TS_NS]]]

    schedule_group = [2, SCHEDULE_WINDOWS, SCHEDULE_CREATED_TS,
                      SCHEDULE_MODIFIED_TS, 1]
    schedule_group_null = [2, SCHEDULE_WINDOWS_NULL_TIMES, SCHEDULE_CREATED_TS,
                           SCHEDULE_MODIFIED_TS, 1]
    quota_group = [2, [6, 0], quot_40, QUOTAS_CREATED_TS, now_q]
    quota_group_no60 = [2, None, quot_40, QUOTAS_CREATED_TS, now_q]
    quota_group_int6 = [2, 6, quot_40, QUOTAS_CREATED_TS, now_q]

    cases = [
        # Exact structure from DevTools (schedule + quota + null + null + [1] + supervision)
        ("A: full body like DevTools (original)",
         [[None, ts()], [schedule_group, [quota_group], None, None, [1], supervision]]),

        # Null out [0,0] start/end times in schedule
        ("B: null start/end times in schedule",
         [[None, ts()], [schedule_group_null, [quota_group], None, None, [1], supervision]]),

        # Skip schedule (null instead)
        ("C: schedule=null",
         [[None, ts()], [None, [quota_group], None, None, [1], supervision]]),

        # [6, 0] replaced by just 6
        ("D: quota_group[1]=6 (scalar)",
         [[None, ts()], [schedule_group, [quota_group_int6], None, None, [1], supervision]]),

        # [6, 0] replaced by null
        ("E: quota_group[1]=null",
         [[None, ts()], [schedule_group, [quota_group_no60], None, None, [1], supervision]]),

        # Minimal: just [[quota_group]]
        ("F: minimal [[quota_group]]",
         [[quota_group]]),

        # No outer timestamp wrapper
        ("G: no outer [null,ts] wrapper",
         [[schedule_group, [quota_group], None, None, [1], supervision]]),

        # supervision as [ts_sec, ts_ns] merged to single int64-ish
        ("H: supervision ts as 14-digit string",
         [[None, ts()], [schedule_group, [quota_group], None, None, [1],
                         [[SUPERVISION_MODE_ID, 1, 2, "1704391266952246000"]]]]),

        # supervision ts as single int
        ("I: supervision ts as int",
         [[None, ts()], [schedule_group, [quota_group], None, None, [1],
                         [[SUPERVISION_MODE_ID, 1, 2, 1704391266952]]]]),

        # No supervision
        ("J: no supervision entry",
         [[None, ts()], [schedule_group, [quota_group], None, None, [1]]]),

        # No [1] flag and no supervision
        ("K: no [1] and no supervision",
         [[None, ts()], [schedule_group, [quota_group], None, None]]),
    ]

    async with aiohttp.ClientSession() as session:
        for label, body in cases:
            headers = build_headers(cookies, sapisid)
            await probe(session, headers, label, body)

    print("\nDone.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python probe_put_variants.py <cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
