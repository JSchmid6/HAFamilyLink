"""Probe additional endpoints for overall screen time control."""
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
ts = int(time.time() * 1000)
digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
headers = {
    "Authorization": f"SAPISIDHASH {ts}_{digest}",
    "Origin": ORIGIN,
    "X-Goog-Api-Key": KEY,
    "Cookie": cookie_str,
    "User-Agent": UA,
    "Content-Type": "application/json",
}

child_id = "112452138243419815198"

PATHS = [
    f"/people/{child_id}/screentime",
    f"/people/{child_id}/screenTime",
    f"/people/{child_id}/dailyLimit",
    f"/people/{child_id}:getScreenTime",
    f"/people/{child_id}:getDailyScreenTime",
    f"/supervision/{child_id}/settings",
    f"/families/mine/supervisionSettings",
    f"/people/{child_id}/usageLimits",
    f"/people/{child_id}/deviceScreenTime",
    f"/people/{child_id}/screenTimeSettings",
    f"/people/{child_id}/timeSettings",
    f"/people/{child_id}/appsAndUsage",
    f"/people/{child_id}/appLimits",
]

with httpx.Client(timeout=15) as client:
    for path in PATHS:
        r = client.get(BASE + path, headers=headers)
        if r.status_code == 200:
            print(f"  {path}: HTTP {r.status_code} ✓")
            print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:500])
        else:
            print(f"  {path}: HTTP {r.status_code}")
