"""
Test JSON and JSPB PUT variants for timeLimit:update endpoint.
"""
import asyncio
import hashlib
import json
import time
from pathlib import Path
import aiohttp

CHILD_ID = "112452138243419815198"
API_BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
EXT223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"
COOKIE_PATH = r"C:\Users\Joche\Downloads\familylink.google.com.cookies.json"


def mk_headers(cookies, sapisid, ct):
    ts = int(time.time() * 1000)
    d = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return {
        "Authorization": f"SAPISIDHASH {ts}_{d}",
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Origin": ORIGIN,
        "Content-Type": ct,
        "x-goog-ext-223261916-bin": EXT223,
        "x-goog-ext-202964622-bin": EXT202,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }


def ts():
    return str(int(time.time() * 1000))


# All quota entries (current state – Monday=40)
ENTRIES_JSON = [
    {"id": "CAEQAQ", "effectiveDay": "monday",
     "state": "timeLimitOn", "usageQuotaMins": 40},
    {"id": "CAEQAg", "effectiveDay": "tuesday",
     "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQAw", "effectiveDay": "wednesday",
     "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBA", "effectiveDay": "thursday",
     "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBQ", "effectiveDay": "friday",
     "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBg", "effectiveDay": "saturday",
     "state": "timeLimitOn", "usageQuotaMins": 90},
    {"id": "CAEQBw", "effectiveDay": "sunday",
     "state": "timeLimitOn", "usageQuotaMins": 90},
]

# schedule windows
SCHEDULE_WINDOWS = [
    ["CAEQAQ", 1, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQAg", 2, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQAw", 3, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQBA", 4, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQBQ", 5, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQBg", 6, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
    ["CAEQBw", 7, 2, [0, 0], [3, 0], "1716144515214", "1716144515214",
     "51a4ee09-ba93-42f6-8eaa-d04433152f7f"],
]

# JSPB quotas
QUOTAS_JSPB = [
    ["CAEQAQ", 1, 2, 40, "1691759143732", "1771690094053"],
    ["CAEQAg", 2, 2, 30, "1691759143732", "1758601179250"],
    ["CAEQAw", 3, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBA", 4, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBQ", 5, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBg", 6, 2, 90, "1691853135824", "1716920233606"],
    ["CAEQBw", 7, 2, 90, "1691853135824", "1716920233606"],
]

SUPERVISION = ["51a4ee09-ba93-42f6-8eaa-d04433152f7f", 1, 2,
               ["1704391266", 952246000]]

# ────────────────────────────────────────────────────────────────────────────────


def make_cases():
    now = ts()

    # JSON bodies
    json_minimal = json.dumps(
        {"timeLimit": {"timeUsageLimits": [{"entries": ENTRIES_JSON}]}}
    )
    json_full = json.dumps({
        "timeLimit": {
            "timeUsageLimits": [{
                "state": "timeLimitOn",
                "resetsAt": {"hour": 6, "minute": 0},
                "entries": ENTRIES_JSON,
            }]
        }
    })
    # JSON with update mask
    json_with_mask = json.dumps({
        "timeLimit": {
            "timeUsageLimits": [{
                "state": "timeLimitOn",
                "resetsAt": {"hour": 6, "minute": 0},
                "entries": ENTRIES_JSON,
            }]
        },
        "updateMask": "timeLimit.timeUsageLimits"
    })

    # JSPB: skip schedule section (null), only quota
    jspb_no_schedule = json.dumps([
        [None, now],
        [None,
         [[2, [6, 0], QUOTAS_JSPB, "1691759143732", now]],
         None, None, [1], [SUPERVISION]]
    ])

    # JSPB: with schedule, correct resetsAt=[6,0]
    jspb_full = json.dumps([
        [None, now],
        [[2, SCHEDULE_WINDOWS, "1704391266952", "1716144515214", 1],
         [[2, [6, 0], QUOTAS_JSPB, "1691759143732", now]],
         None, None, [1], [SUPERVISION]]
    ])

    # JSPB with httpMethod=PUT (not POST with param)
    # Testing via different param names
    cases = [
        ("JSON minimal entries", "application/json", "PUT", json_minimal),
        ("JSON full with resetsAt", "application/json", "PUT", json_full),
        ("JSON with updateMask", "application/json", "PUT", json_with_mask),
        ("JSPB no-schedule only quotas", "application/json+protobuf", "PUT", jspb_no_schedule),
        ("JSPB full schedule+quotas", "application/json+protobuf", "PUT", jspb_full),
    ]
    return cases


async def main():
    cookies = {c["name"]: c["value"]
               for c in json.loads(Path(COOKIE_PATH).read_text())}
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"

    async with aiohttp.ClientSession() as session:
        for label, ct, method, body in make_cases():
            h = mk_headers(cookies, sapisid, ct)
            # Try both httpMethod and $httpMethod as query param
            for param_name in ["$httpMethod", "httpMethod"]:
                async with session.post(
                    url, headers=h,
                    params={param_name: method},
                    data=body
                ) as r:
                    resp = await r.text()
                    ok = "OK" if r.status == 200 else "FAIL"
                    print(f"[{ok}] {label} (param={param_name}): HTTP {r.status}")
                    if r.status != 200:
                        print(f"     {resp[:300]}")
                    else:
                        print(f"     SUCCESS! Response: {resp[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
