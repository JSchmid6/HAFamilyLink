"""
Correct PUT body for timeLimit:update based on proto schema discovery:
  outer: [api_header, update]
  update = TimeLimitUpdate: [window_update, usage_updates]
  usage_updates: repeated UsageUpdate with new_state and new_entries

Usage: .venv\Scripts\python.exe scripts\probe_correct_jspb.py <cookies.json>
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

def mk_h(cookies, sapisid):
    ts = int(time.time() * 1000)
    d = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return {
        "Authorization": f"SAPISIDHASH {ts}_{d}", "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY, "Origin": ORIGIN,
        "Content-Type": "application/json+protobuf",
        "x-goog-ext-223261916-bin": EXT223,
        "x-goog-ext-202964622-bin": EXT202,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }

# Keep quota at current value (40 for Monday) = safe no-change test
ALL_ENTRIES_6 = [  # 6 fields: [id, day, state, quota, stateTs, quotaTs]
    ["CAEQAQ", 1, 2, 40, "1691759143732", "1771690094053"],
    ["CAEQAg", 2, 2, 30, "1691759143732", "1758601179250"],
    ["CAEQAw", 3, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBA", 4, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBQ", 5, 2, 30, "1691759143732", "1716920233606"],
    ["CAEQBg", 6, 2, 90, "1691853135824", "1716920233606"],
    ["CAEQBw", 7, 2, 90, "1691853135824", "1716920233606"],
]
ALL_ENTRIES_4 = [  # 4 fields: [id, day, state, quota] (no timestamps)
    ["CAEQAQ", 1, 2, 40], ["CAEQAg", 2, 2, 30], ["CAEQAw", 3, 2, 30],
    ["CAEQBA", 4, 2, 30], ["CAEQBQ", 5, 2, 30], ["CAEQBg", 6, 2, 90], ["CAEQBw", 7, 2, 90],
]
MONDAY_ENTRY_6 = [["CAEQAQ", 1, 2, 40, "1691759143732", "1771690094053"]]
MONDAY_ENTRY_4 = [["CAEQAQ", 1, 2, 40]]

def make_cases():
    ts_now = str(int(time.time() * 1000))

    # Vary api_header
    api_headers = [
        ("ah=[null,null]",     [None, None]),
        ("ah=[null,ts]",       [None, ts_now]),   # like DevTools captured format
        ("ah=null",            None),
        ("ah=[]",              []),
    ]

    # Vary usage_update structure
    # Based on errors: usage_update has new_state (field1) and new_entries (field2 repeated)
    usage_updates = [
        ("ua=[2,entries_6]",          [2, ALL_ENTRIES_6]),
        ("ua=[2,entries_4]",          [2, ALL_ENTRIES_4]),
        ("ua=[null,entries_6]",        [None, ALL_ENTRIES_6]),
        ("ua=[2,mon6]",               [2, MONDAY_ENTRY_6]),
        ("ua=[2,mon4]",               [2, MONDAY_ENTRY_4]),
        ("ua=[[2,entries_6]]",        [[2, ALL_ENTRIES_6]]),   # wrapped
        # resetsAt inserted at field 2 (message field [6,0])
        ("ua=[2,[6,0],entries_4]",    [2, [6, 0], ALL_ENTRIES_4]),
    ]

    # Vary update (TimeLimitUpdate) structure
    #   update = [window_update=field1, usage_updates=field2 (repeated)]
    def make_updates(ua):
        return [
            ("upd=[null,[ua]]",   [None, [ua]]),      # null window + one usage_update
            ("upd=[null,ua]",      [None, ua]),         # null window + usage_update (no repeat wrap)
            ("upd=[[ua]]",          [[ua]]),            # just wrapped usage_update
        ]

    cases = []
    for ua_label, ua in usage_updates:
        for upd_label, upd in make_updates(ua):
            for ah_label, ah in api_headers:
                label = f"{ua_label} | {upd_label} | {ah_label}"
                body = json.dumps([ah, upd])
                cases.append((label, body))
    return cases


async def run_probe(session, cookies, sapisid, label, body, url, params):
    h = mk_h(cookies, sapisid)
    async with session.post(url, headers=h, params=params, data=body) as r:
        resp = await r.text()
        if r.status == 200:
            print(f"  [OK ] {label}")
            print(f"        Response: {resp[:200]}")
            return True
        else:
            # One-line error summary
            first_err = resp.replace("\n", " ")[:120]
            print(f"  [400] {label}: {first_err}")
            return False


async def main():
    cookies = {c["name"]: c["value"] for c in json.loads(Path(COOKIE_PATH).read_text())}
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
    params = {"$httpMethod": "PUT"}

    cases = make_cases()
    print(f"Testing {len(cases)} variants...")

    async with aiohttp.ClientSession() as session:
        for label, body in cases:
            ok = await run_probe(session, cookies, sapisid, label, body, url, params)
            if ok:
                print(f"\n*** SUCCESS! ***\nLabel: {label}\nBody: {body[:400]}")
                break

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
