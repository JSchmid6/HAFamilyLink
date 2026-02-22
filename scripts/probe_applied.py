"""Check appliedTimeLimits after probe + test outer-request limit placement."""
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
        return {c["name"]: c["value"] for c in json.load(f)}


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


async def main() -> None:
    cookies = load_cookies(sys.argv[1])
    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as s:
        # 1. Check current appliedTimeLimits (has our probe changed anything?)
        h = make_headers(cookies)
        url = f"{BASE}/people/{CHILD_ID}/appliedTimeLimits?capabilities=TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
        async with s.get(url, headers=h) as r:
            body = await r.json()
            print(f"appliedTimeLimits: {r.status}")
            try:
                for dev in body[1]:
                    if EMILIO_DEV in str(dev):
                        print(f"Emilio entry: {json.dumps(dev)[:600]}")
            except Exception as e:
                print(f"Parse error: {e}")
                print(json.dumps(body)[:400])

        print()

        # 2. Test outer-request fields and additional override fields
        create_url = f"{BASE}/people/{CHILD_ID}/timeLimitOverrides:batchCreate"
        tests = [
            # outer field 2 = limit (not in override)
            ("[outer2=90]",          [None, 90, [[None, None, 1, EMILIO_DEV]]]),
            # outer field 4 = limit
            ("[outer4=90]",          [None, None, [[None, None, 1, EMILIO_DEV]], 90]),
            # override idx5=90 confirmed accepted - what does response show?
            ("[idx5=90,act=1]",      [None, None, [[None, None, 1, EMILIO_DEV, None, 90]]]),
            # override idx5=90 with action=2
            ("[idx5=90,act=2]",      [None, None, [[None, None, 2, EMILIO_DEV, None, 90]]]),
            # override idx7=90 (field 8)  
            ("[idx7=90,act=1]",      [None, None, [[None, None, 1, EMILIO_DEV, None, None, None, 90]]]),
        ]
        for label, payload in tests:
            h = make_headers(cookies)
            async with s.post(create_url, json=payload, headers=h) as r:
                status = r.status
                body_text = await r.text()
                if status == 200:
                    try:
                        parsed = json.loads(body_text)
                        print(f"  200 {label}:\n{json.dumps(parsed, indent=2)}")
                    except Exception:
                        print(f"  200 {label}: {body_text[:400]}")
                else:
                    msg = ""
                    try:
                        msg = json.loads(body_text).get("error", {}).get("message", "")
                    except Exception:
                        msg = body_text[:200]
                    print(f"  {status} {label}: {msg[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
