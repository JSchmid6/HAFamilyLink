"""Probe capabilityTimeout and bedtime endpoints.

Device capabilities include:
  capabilityTimeout
  capabilityBedtime
  capabilityLockWithDeadline
  capabilitySchoolTimeMode
  capabilityTimeLimitUnlockUntilLockDeadline

These suggest the device-level time limit IS controllable - just via different paths.
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


# Emilio device: aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq
CHILD_ID = "112452138243419815198"
DEV_ID = "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq"

with httpx.Client(timeout=15) as client:
    print("=== Timeout-related GET endpoints ===")
    for path in [
        f"/devices/{DEV_ID}:getTimeout",
        f"/devices/{DEV_ID}/timeout",
        f"/people/{CHILD_ID}:getTimeout",
        f"/people/{CHILD_ID}/timeout",
        f"/people/{CHILD_ID}/bedtime",
        f"/people/{CHILD_ID}:getBedtime",
        f"/devices/{DEV_ID}/bedtime",
        f"/people/{CHILD_ID}/schedule",
        f"/people/{CHILD_ID}/schooltime",
        f"/people/{CHILD_ID}/lockDeadline",
        f"/people/{CHILD_ID}:getLockDeadline",
    ]:
        r = client.get(BASE + path, headers=fresh_headers())
        print(f"  GET {path}: {r.status_code}", "✓" if r.status_code == 200 else "")
        if r.status_code == 200:
            print(json.dumps(r.json(), indent=4)[:500])

    print("\n=== Timeout-related POST probes (safe - no real change) ===")
    # Try posting an empty/invalid body just to see if endpoint exists (non-404)
    for path, body in [
        (f"/devices/{DEV_ID}:setTimeout", "{}"),
        (f"/devices/{DEV_ID}:lockWith", "{}"),
        (f"/devices/{DEV_ID}:lockWithDeadline", "{}"),
        (f"/people/{CHILD_ID}:setTimeout", "{}"),
        (f"/people/{CHILD_ID}:lockWithDeadline", "{}"),
        (f"/people/{CHILD_ID}:setBedtime", "{}"),
        (f"/people/{CHILD_ID}:setSchoolTime", "{}"),
        (f"/people/{CHILD_ID}/devices/{DEV_ID}:setTimeout", "{}"),
        (f"/people/{CHILD_ID}/devices/{DEV_ID}:lockWithDeadline", "{}"),
    ]:
        r = client.post(BASE + path, headers=fresh_headers("application/json"), content=body)
        print(f"  POST {path}: {r.status_code}", "✓" if r.status_code not in (404, 405) else "")
        if r.status_code not in (404, 405):
            print(f"    Response: {r.text[:300]}")

    print("\n=== Try different API origin / referer ===")
    for alt_origin in [
        "https://families.google.com",
        "https://myaccount.google.com",
    ]:
        ts = int(time.time() * 1000)
        digest = hashlib.sha1(f"{ts} {sapisid} {alt_origin}".encode()).hexdigest()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        h = {
            "Authorization": f"SAPISIDHASH {ts}_{digest}",
            "Origin": alt_origin,
            "Referer": alt_origin + "/",
            "X-Goog-Api-Key": KEY,
            "Cookie": cookie_str,
            "User-Agent": UA,
            "Content-Type": "application/json",
        }
        r = client.get(f"{BASE}/families/mine/members", headers=h)
        print(f"  Origin={alt_origin}: members HTTP {r.status_code}")
