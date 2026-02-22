"""
Probe GET /timeLimit endpoint and decode the response structure.
Usage: .\.venv\Scripts\python.exe scripts\probe_timelimit.py <cookies.json>
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


def build_sapisidhash(sapisid: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def load_cookies(path: str) -> dict[str, str]:
    data = json.loads(Path(path).read_text())
    return {c["name"]: c["value"] for c in data}


async def main(cookie_path: str) -> None:
    cookies = load_cookies(cookie_path)
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    auth = build_sapisidhash(sapisid)

    headers = {
        "Authorization": auth,
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Origin": ORIGIN,
        "x-goog-ext-223261916-bin": GOOG_EXT_223,
        "x-goog-ext-202964622-bin": GOOG_EXT_202,
    }

    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers["Cookie"] = cookie_header

    async with aiohttp.ClientSession() as session:

        # ── 1. GET /timeLimit (plain JSON) ──────────────────────────────────
        print("=" * 60)
        print("1. GET /timeLimit  (Content-Type: application/json)")
        url = f"{API_BASE}/people/{CHILD_ID}/timeLimit"
        params = {"$alt": "json"}
        h = {**headers, "Content-Type": "application/json"}
        async with session.get(url, headers=h, params=params) as r:
            print(f"   Status: {r.status}")
            body = await r.text()
            print(f"   Body ({len(body)} chars):\n{body[:2000]}")

        # ── 2. GET /timeLimit  (JSPB protobuf) ──────────────────────────────
        print()
        print("=" * 60)
        print("2. GET /timeLimit  (Content-Type: application/json+protobuf)")
        h2 = {**headers, "Content-Type": "application/json+protobuf"}
        async with session.get(url, headers=h2) as r:
            print(f"   Status: {r.status}")
            body = await r.text()
            print(f"   Body ({len(body)} chars):\n{body[:3000]}")

        # ── 3. Try to decode the JSPB response structure ─────────────────────
        if r.status == 200:
            print()
            print("=" * 60)
            print("3. Parsed JSPB response:")
            try:
                data = json.loads(body)
                print(json.dumps(data, indent=2)[:4000])
            except Exception as e:
                print(f"   JSON parse error: {e}")

        # ── 4. Minimal PUT test: same body as captured, but verify HTTP 200 ──
        print()
        print("=" * 60)
        print("4. Test PUT /timeLimit:update with captured body structure")
        update_url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
        params_put = {"$httpMethod": "PUT"}
        h3 = {**headers, "Content-Type": "application/json+protobuf"}

        # Use the exact request body captured from DevTools:
        # Monday (day 1) quota = 40 min as observed in timelimits.txt
        # We'll just replay this to confirm it works; DO NOT CHANGE quota here
        # This is Emilio's timeLimit – captured 2026-02-21
        captured_body = ('[[null,"1771690094598"],[[2,[["CAEQBA",4,2,[0,0],[3,0],'
                         '"1716144515214","1716144515214","51a4ee09-ba93-42f6-8eaa-d04433152f7f"],'
                         '["CAEQBQ",5,2,[0,0],[3,0],"1716144515214","1716144515214",'
                         '"51a4ee09-ba93-42f6-8eaa-d04433152f7f"],["CAEQAQ",1,2,[0,0],[3,0],'
                         '"1716144515214","1716144515214","51a4ee09-ba93-42f6-8eaa-d04433152f7f"],'
                         '["CAEQBg",6,2,[0,0],[3,0],"1716144515214","1716144515214",'
                         '"51a4ee09-ba93-42f6-8eaa-d04433152f7f"],["CAEQBw",7,2,[0,0],[3,0],'
                         '"1716144515214","1716144515214","51a4ee09-ba93-42f6-8eaa-d04433152f7f"],'
                         '["CAEQAg",2,2,[0,0],[3,0],"1716144515214","1716144515214",'
                         '"51a4ee09-ba93-42f6-8eaa-d04433152f7f"],["CAEQAw",3,2,[0,0],[3,0],'
                         '"1716144515214","1716144515214","51a4ee09-ba93-42f6-8eaa-d04433152f7f"]],'
                         '"1704391266952","1716144515214",1],[[2,[6,0],[["CAEQBA",4,2,30,'
                         '"1691759143732","1716920233606"],["CAEQBQ",5,2,30,"1691759143732",'
                         '"1716920233606"],["CAEQAQ",1,2,40,"1691759143732","1771690094053"],'
                         '["CAEQBg",6,2,90,"1691853135824","1716920233606"],["CAEQBw",7,2,90,'
                         '"1691853135824","1716920233606"],["CAEQAg",2,2,30,"1691759143732",'
                         '"1758601179250"],["CAEQAw",3,2,30,"1691759143732","1716920233606"]],'
                         '"1691759143732","1771690094053"]],null,null,[1],[["51a4ee09-ba93-42f6-'
                         '8eaa-d04433152f7f",1,2,["1704391266",952246000]]]]]]')

        print("   NOTE: Replaying captured body (no actual change to quota)")
        async with session.post(update_url, headers=h3, params=params_put,
                                data=captured_body) as r:
            print(f"   Status: {r.status}")
            resp = await r.text()
            print(f"   Response: {resp[:500]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python probe_timelimit.py <path-to-cookies.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
