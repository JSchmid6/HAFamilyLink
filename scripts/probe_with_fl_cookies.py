"""Probe with familylink.google.com cookies – tries all SAPISID/origin combos.

Usage:
    python scripts/probe_with_fl_cookies.py <fl_cookies> [myaccount_cookies]

Example:
    python scripts/probe_with_fl_cookies.py \
        "C:/Users/Joche/Downloads/familylink.google.com.cookies.json" \
        "C:/Users/Joche/Downloads/myaccount.google.com.cookies (5).json"
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time

import aiohttp

FL_COOKIES_FILE = sys.argv[1] if len(sys.argv) > 1 else "fl_cookies.json"
MA_COOKIES_FILE = sys.argv[2] if len(sys.argv) > 2 else None

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
CHILD_ID = "112452138243419815198"
DEVICE_ID = "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq"

ORIGINS = [
    "https://familylink.google.com",
    "https://families.google.com",
    "https://myaccount.google.com",
]

# Captured static ext headers from browser DevTools
EXT_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"


def load_cookies(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return {c["name"]: c["value"] for c in json.load(f)}


def sapisid_hash(sapisid: str, origin: str) -> str:
    ts = str(int(time.time() * 1000))
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def cookie_str(cdict: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cdict.items())


def verify_captured_hash(cookies: dict[str, str], label: str) -> None:
    """Verify which origin matches the captured SAPISIDHASH from the browser."""
    captured_ts = "1771683731332"
    captured_hash = "9ba3c7f03d9b9d4627bd17780c01ce7c97977318"
    print(f"\n=== Verifying captured hash against [{label}] cookies ===")
    for name in ["__Secure-3PAPISID", "SAPISID", "__Secure-1PAPISID"]:
        sapisid = cookies.get(name, "")
        if not sapisid:
            continue
        for origin in ORIGINS:
            digest = hashlib.sha1(
                f"{captured_ts} {sapisid} {origin}".encode()
            ).hexdigest()
            match = "✓ MATCH!" if digest == captured_hash else ""
            if match:
                print(f"  {match} cookie={name}, origin={origin}")
                print(f"  sapisid={sapisid[:12]}...")


async def probe(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    origin: str,
    label: str,
) -> bool:
    """Try GET appliedTimeLimits. Return True on success."""
    sapisid = (
        cookies.get("__Secure-3PAPISID")
        or cookies.get("SAPISID")
        or cookies.get("__Secure-1PAPISID")
        or ""
    )
    if not sapisid:
        return False

    url = f"{BASE}/people/{CHILD_ID}/appliedTimeLimits"
    params = {"capabilities": "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"}
    headers = {
        "Authorization": sapisid_hash(sapisid, origin),
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json+protobuf",
        "Origin": origin,
        "Referer": f"{origin}/",
        "Cookie": cookie_str(cookies),
        "x-goog-ext-223261916-bin": EXT_223,
        "x-goog-ext-202964622-bin": EXT_202,
    }

    async with session.get(url, params=params, headers=headers) as r:
        status = r.status
        body = await r.text()

    print(f"  [{label}] origin={origin} → {status}")
    if status == 200:
        try:
            data = json.loads(body)
            print("  ✓ SUCCESS!")
            print(json.dumps(data, indent=2)[:2000])
        except Exception:
            print(f"  body: {body[:500]}")
        return True
    elif status not in (401, 403):
        print(f"  body: {body[:200]}")
    return False


async def probe_batch_create(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    origin: str,
    label: str,
    device_id: str,
    limit_ms: int,
) -> bool:
    sapisid = (
        cookies.get("__Secure-3PAPISID")
        or cookies.get("SAPISID")
        or cookies.get("__Secure-1PAPISID")
        or ""
    )
    url = f"{BASE}/people/{CHILD_ID}/timeLimitOverrides:batchCreate"
    headers = {
        "Authorization": sapisid_hash(sapisid, origin),
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": "application/json+protobuf",
        "Origin": origin,
        "Referer": f"{origin}/",
        "Cookie": cookie_str(cookies),
        "x-goog-ext-223261916-bin": EXT_223,
        "x-goog-ext-202964622-bin": EXT_202,
    }

    print(f"\n{'='*60}")
    print(f"POST batchCreate [{label}] origin={origin}")
    for label2, payload in [
        ("empty", {}),
        ("timeLimitOverrides[]", {"timeLimitOverrides": [{"deviceId": device_id, "dailyLimitInMs": limit_ms}]}),
        ("requests[]", {"requests": [{"deviceId": device_id, "timeLimitOverride": {"dailyLimitInMs": limit_ms}}]}),
    ]:
        async with session.post(url, json=payload, headers=headers) as r:
            status = r.status
            body = await r.text()
        print(f"  {label2} → {status}")
        if status not in (401, 403):
            print(f"  body: {body[:600]}")
        if status == 200:
            print("  ✓ SUCCESS!")
            return True
    return False


async def main() -> None:
    # Load cookies
    fl_cookies = load_cookies(FL_COOKIES_FILE)
    print(f"familylink cookies ({len(fl_cookies)}): {list(fl_cookies.keys())}")

    ma_cookies: dict[str, str] = {}
    if MA_COOKIES_FILE:
        ma_cookies = load_cookies(MA_COOKIES_FILE)
        print(f"myaccount cookies ({len(ma_cookies)}): {list(ma_cookies.keys())}")

    # Merge: familylink cookies take priority where domains overlap
    merged = {**ma_cookies, **fl_cookies}
    print(f"\nMerged cookie count: {len(merged)}")

    # Verify which origin matches the captured hash
    for label, cdict in [("familylink", fl_cookies), ("myaccount", ma_cookies), ("merged", merged)]:
        if cdict:
            verify_captured_hash(cdict, label)

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        print(f"\n{'='*60}")
        print("GET appliedTimeLimits – trying all cookie/origin combinations")

        found = False
        for label, cdict in [("familylink", fl_cookies), ("myaccount", ma_cookies), ("merged", merged)]:
            if not cdict:
                continue
            for origin in ORIGINS:
                ok = await probe(session, cdict, origin, label)
                if ok:
                    found = True
                    # Now probe batchCreate with the winning combo
                    await probe_batch_create(session, cdict, origin, label, DEVICE_ID, 7200000)
                    break
            if found:
                break

        if not found:
            print("\nAll combinations failed. Printing available SAPISID cookies:")
            for label, cdict in [("familylink", fl_cookies), ("myaccount", ma_cookies)]:
                for name in ["__Secure-3PAPISID", "SAPISID", "__Secure-1PAPISID", "__Secure-3PSID", "SID"]:
                    val = cdict.get(name)
                    if val:
                        print(f"  [{label}] {name} = {val[:20]}...")


if __name__ == "__main__":
    asyncio.run(main())
