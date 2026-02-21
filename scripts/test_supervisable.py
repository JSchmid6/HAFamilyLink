"""Verify supervisable parsing and bulk update logic with live data."""
import asyncio
import hashlib
import json
import sys
import time

sys.path.insert(0, r"C:\DEV\HAFamilyLink")

from custom_components.familylink.client.parsers import parse_restrictions

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

# Test with Emilio (first child, youngest)
child_id = "112452138243419815198"
child_name = "Emilio"

with httpx.Client(timeout=15) as client:
    r = client.get(
        f"{BASE}/people/{child_id}/appsandusage",
        headers=fresh_headers(),
        params={"capabilities": ["CAPABILITY_APP_USAGE_SESSION", "CAPABILITY_SUPERVISION_CAPABILITIES"]},
    )
    r.raise_for_status()
    data = r.json()

restrictions = parse_restrictions(data)

print(f"=== {child_name} Restrictions ===")
print(f"  Blocked apps:          {len(restrictions['blocked'])} – {restrictions['blocked'][:3]}...")
print(f"  Always-allowed apps:   {len(restrictions['always_allowed'])} – {restrictions['always_allowed'][:3]}...")
print(f"  Limited apps:          {len(restrictions['limited'])} – {[a['app'] + ' (' + str(a.get('limit_minutes', '?')) + 'min)' for a in restrictions['limited'][:3]]}...")
print(f"  Supervisable apps:     {len(restrictions['supervisable'])} (total controllable via bulk)")
print()
print("  First 5 supervisable apps:")
for s in restrictions["supervisable"][:5]:
    print(f"    - {s['title']} ({s['package']})")
print()
print("  All supervisable packages (for bulk update):")
pkgs = [s["package"] for s in restrictions["supervisable"]]
print(f"    {len(pkgs)} packages total")
print(f"    First 3: {pkgs[:3]}")
