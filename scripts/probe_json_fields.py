"""
Step 2: Find the correct JSON field names for timeLimit:update PUT request.
Based on: "Unknown name 'timeLimit': Cannot find field" error.
"""
import asyncio, hashlib, json, time
from pathlib import Path
import aiohttp

CHILD_ID = "112452138243419815198"
API_BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
EXT223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"
COOKIE_PATH = r"C:\Users\Joche\Downloads\familylink.google.com.cookies.json"

ENTRIES = [
    {"id": "CAEQAQ", "effectiveDay": "monday", "state": "timeLimitOn", "usageQuotaMins": 40},
    {"id": "CAEQAg", "effectiveDay": "tuesday", "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQAw", "effectiveDay": "wednesday", "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBA", "effectiveDay": "thursday", "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBQ", "effectiveDay": "friday", "state": "timeLimitOn", "usageQuotaMins": 30},
    {"id": "CAEQBg", "effectiveDay": "saturday", "state": "timeLimitOn", "usageQuotaMins": 90},
    {"id": "CAEQBw", "effectiveDay": "sunday", "state": "timeLimitOn", "usageQuotaMins": 90},
]
USAGE_LIMIT = {"state": "timeLimitOn", "resetsAt": {"hour": 6, "minute": 0}, "entries": ENTRIES}

def mk_h(cookies, sapisid, ct="application/json"):
    ts = int(time.time() * 1000)
    d = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return {"Authorization": f"SAPISIDHASH {ts}_{d}", "X-Goog-AuthUser": "0",
            "X-Goog-Api-Key": API_KEY, "Origin": ORIGIN, "Content-Type": ct,
            "x-goog-ext-223261916-bin": EXT223, "x-goog-ext-202964622-bin": EXT202,
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}

CASES_JSON = [
    ("timeUsageLimits",         {"timeUsageLimits": [USAGE_LIMIT]}),
    ("usageLimits",             {"usageLimits": [USAGE_LIMIT]}),
    ("screenTimeLimits",        {"screenTimeLimits": [USAGE_LIMIT]}),
    ("usageLimit",              {"usageLimit": USAGE_LIMIT}),
    ("usageLimitUpdate",        {"usageLimitUpdate": {"entries": ENTRIES}}),
    ("update",                  {"update": {"timeUsageLimits": [USAGE_LIMIT]}}),
    ("updates",                 {"updates": [{"timeUsageLimits": [USAGE_LIMIT]}]}),
    ("entries",                 {"entries": ENTRIES}),
    ("timeLimitUpdate",         {"timeLimitUpdate": {"timeUsageLimits": [USAGE_LIMIT]}}),
    ("dailyLimits",             {"dailyLimits": ENTRIES}),
    ("usageQuota",              {"usageQuota": ENTRIES}),
    ("screenTimeLimit",         {"screenTimeLimit": USAGE_LIMIT}),
    ("timeLimitConfig",         {"timeLimitConfig": {"timeUsageLimits": [USAGE_LIMIT]}}),
    ("dailyUsageLimits",        {"dailyUsageLimits": ENTRIES}),
    # Send just JSPB without the outer [null, ts] wrapper
    ("JSPB_bare_payload", None),  # special case below
]

# JSPB bare payload (no [null, ts] wrapper) - direct TimeLimit JSPB
QUOTAS_JSPB = [
    ["CAEQAQ", 1, 2, 40, "1691759143732", "1771690094053"],
    ["CAEQAg", 2, 2, 30, "1691759143732", "1758601179250"],
    ["CAEQAw", 3, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBA", 4, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBQ", 5, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBg", 6, 2, 90, "1691853135824", "1716920233606"],
    ["CAEQBw", 7, 2, 90, "1691853135824", "1716920233606"],
]

async def main():
    cookies = {c["name"]: c["value"] for c in json.loads(Path(COOKIE_PATH).read_text())}
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
    params = {"$httpMethod": "PUT"}

    async with aiohttp.ClientSession() as session:
        for label, body_dict in CASES_JSON:
            if label == "JSPB_bare_payload":
                # Try without outer [null, ts] wrapper: bare TimeLimit JSPB
                now = str(int(time.time() * 1000))
                bodies = [
                    ("JSPB bare list [schedule,quotas,null,null,[1],[sup]]",
                     "application/json+protobuf",
                     json.dumps([
                         [2, [["CAEQAQ",1,2,[0,0],[3,0],"1716144515214","1716144515214","51a4ee09-ba93-42f6-8eaa-d04433152f7f"]],
                          "1704391266952","1716144515214",1],
                         [[2,[6,0],QUOTAS_JSPB,"1691759143732",now]],
                         None, None, [1],
                         [["51a4ee09-ba93-42f6-8eaa-d04433152f7f",1,2,["1704391266",952246000]]]
                     ])),
                    ("JSPB just [[quota_group]]",
                     "application/json+protobuf",
                     json.dumps([[2,[6,0],QUOTAS_JSPB,"1691759143732",now]])),
                    ("JSPB only quota entries list",
                     "application/json+protobuf",
                     json.dumps([2,[6,0],QUOTAS_JSPB,"1691759143732",now])),
                ]
                for lbl, ct, body in bodies:
                    h = mk_h(cookies, sapisid, ct)
                    async with session.post(url, headers=h, params=params, data=body) as r:
                        resp = await r.text()
                        is_ok = r.status == 200
                        mark = "OK" if is_ok else "FAIL"
                        print(f"[{mark}] {lbl}: {r.status}")
                        if not is_ok:
                            print(f"     {resp[:250]}")
                        else:
                            print(f"     RESPONSE: {resp[:300]}")
                continue

            body_str = json.dumps(body_dict)
            h = mk_h(cookies, sapisid)
            async with session.post(url, headers=h, params=params, data=body_str) as r:
                resp = await r.text()
                # Look for "Cannot find field" vs other errors
                if "Cannot find field" in resp:
                    # Extract which field was not found
                    import re
                    fields = re.findall(r'Unknown name "([^"]+)"', resp)
                    print(f"[FAIL-field] {label}: unknown={fields}")
                elif r.status == 200:
                    print(f"[OK] {label}: {resp[:200]}")
                else:
                    print(f"[FAIL] {label}: {r.status} - {resp[:150]}")

asyncio.run(main())
