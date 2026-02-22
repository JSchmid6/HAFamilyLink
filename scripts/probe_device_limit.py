"""Deep-probe for device-level screen time endpoints.

Tests all three children and tries device-level endpoints as well as
any special POST endpoints that could set the daily device limit.
"""
import hashlib
import json
import time
import httpx

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
ORIGIN = "https://familylink.google.com"
KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"

COOKIE_FILE = r"C:\Users\Joche\Downloads\myaccount.google.com.cookies (5).json"

cookies = json.load(open(COOKIE_FILE))
sapisid = next(c["value"] for c in cookies if c["name"] == "SAPISID")


def fresh_headers(ct="application/json"):
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {
        "Authorization": f"SAPISIDHASH {ts}_{digest}",
        "Origin": ORIGIN,
        "X-Goog-Api-Key": KEY,
        "Cookie": cookie_str,
        "User-Agent": UA,
        "Content-Type": ct,
    }


CHILDREN = {
    "112452138243419815198": "Emilio",
    "115307393794918034742": "Ronja",
    "105266986367418000092": "Lennard",
}

with httpx.Client(timeout=15) as client:
    for child_id, name in CHILDREN.items():
        print(f"\n{'='*60}")
        print(f"Child: {name} ({child_id})")
        print('='*60)

        # Get appsandusage
        r = client.get(
            f"{BASE}/people/{child_id}/appsandusage",
            headers=fresh_headers(),
            params={"capabilities": ["CAPABILITY_APP_USAGE_SESSION", "CAPABILITY_SUPERVISION_CAPABILITIES"]},
        )
        print(f"  appsandusage: HTTP {r.status_code}")
        if r.status_code != 200:
            continue
        data = r.json()

        # Show device info
        devices = data.get("deviceInfo", [])
        print(f"  Devices registered: {len(devices)}")
        for d in devices:
            dev_id = d.get("deviceId", "")
            model = d.get("displayInfo", {}).get("model", "?")
            friendly = d.get("displayInfo", {}).get("friendlyName", "?")
            caps = d.get("capabilityInfo", {}).get("capabilities", [])
            print(f"    - {friendly} ({model}) id={dev_id[:20]}... caps={caps}")

        # Try device-level endpoints for each registered device
        for d in devices:
            dev_id = d.get("deviceId", "")
            if not dev_id:
                continue
            print(f"\n  --- Device {dev_id[:24]}... ---")
            for path in [
                f"/devices/{dev_id}",
                f"/devices/{dev_id}/screentime",
                f"/devices/{dev_id}/settings",
                f"/devices/{dev_id}/restrictions",
                f"/devices/{dev_id}/dailylimit",
                f"/people/{child_id}/devices/{dev_id}",
                f"/people/{child_id}/devices/{dev_id}/screentime",
                f"/people/{child_id}/devices/{dev_id}/settings",
            ]:
                ro = client.get(BASE + path, headers=fresh_headers())
                status = ro.status_code
                print(f"    GET {path}: {status}", end="")
                if status == 200:
                    print(" ✓")
                    print(json.dumps(ro.json(), indent=4, ensure_ascii=False)[:600])
                else:
                    print()

        # Try POST to set device time limit
        print(f"\n  --- POST endpoints for {name} ---")
        for path, body in [
            (f"/people/{child_id}:setDailyUsageLimit", json.dumps({"dailyUsageLimitMins": 60})),
            (f"/people/{child_id}/apps:setDailyLimit", json.dumps([child_id, [[60, 1]]])),
            (f"/people/{child_id}/devices:setDailyLimit", json.dumps([child_id, [[60, 1]]])),
        ]:
            rp = client.post(BASE + path, headers=fresh_headers("application/json+protobuf"), content=body)
            print(f"    POST {path}: {rp.status_code}")

        # Show all top-level keys in appsandusage
        print(f"\n  Top-level keys: {list(data.keys())}")
