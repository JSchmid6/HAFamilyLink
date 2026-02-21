"""Inspect full deviceInfo and try device-specific endpoints."""
import hashlib
import json
import time
import httpx

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
ORIGIN = "https://familylink.google.com"
KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"

cookies = json.load(open(r"C:\Users\Joche\Downloads\myaccount.google.com.cookies (4).json"))
sapisid = next(c["value"] for c in cookies if c["name"] == "SAPISID")

def fresh_headers():
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {
        "Authorization": f"SAPISIDHASH {ts}_{digest}",
        "Origin": ORIGIN,
        "X-Goog-Api-Key": KEY,
        "Cookie": cookie_str,
        "User-Agent": UA,
        "Content-Type": "application/json",
    }

child_id = "112452138243419815198"

with httpx.Client(timeout=15) as client:
    # Get full appsandusage and look at deviceInfo
    r = client.get(
        f"{BASE}/people/{child_id}/appsandusage",
        headers=fresh_headers(),
        params={"capabilities": ["CAPABILITY_APP_USAGE_SESSION", "CAPABILITY_SUPERVISION_CAPABILITIES"]},
    )
    data = r.json()

    print("=== deviceInfo ===")
    for di in data.get("deviceInfo", []):
        print(json.dumps(di, indent=2, ensure_ascii=False))
        print()

    # Try capabilities endpoint from deviceInfo
    for di in data.get("deviceInfo", []):
        device_id = di.get("deviceId", "")
        caps = di.get("capabilityInfo", {}).get("capabilities", [])
        print(f"Device {device_id}: capabilities = {caps}")

    # Try with different base URLs
    print("\n=== Trying other base URLs ===")
    for alt_base in [
        "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v2",
        "https://families.googleapis.com/v1",
        "https://familylink.googleapis.com/v1",
    ]:
        r2 = client.get(
            f"{alt_base}/families/mine/members",
            headers=fresh_headers(),
        )
        print(f"  {alt_base}: HTTP {r2.status_code}")
        if r2.status_code == 200:
            print(json.dumps(r2.json(), indent=2, ensure_ascii=False)[:500])

    # Try POST to batchUpdate
    print("\n=== Trying POST batch update ===")
    for path in [
        f"/people/{child_id}/apps:batchUpdate",
        f"/people/{child_id}:batchUpdateRestrictions",
        f"/people/{child_id}:setDailyScreenTime",
        f"/people/{child_id}:updateDailyScreenTimeLimit",
    ]:
        r3 = client.post(
            BASE + path,
            headers={**fresh_headers(), "Content-Type": "application/json+protobuf"},
            content="[]",
        )
        print(f"  POST {path}: HTTP {r3.status_code}")

    # Try families-level endpoint for screentime  
    print("\n=== Trying /families/mine/* ===")
    for path in [
        "/families/mine",
        "/families/mine/children",
        "/families/mine/settings",
    ]:
        r4 = client.get(BASE + path, headers=fresh_headers())
        print(f"  {path}: HTTP {r4.status_code}")
        if r4.status_code == 200:
            print(json.dumps(r4.json(), indent=2, ensure_ascii=False)[:500])
