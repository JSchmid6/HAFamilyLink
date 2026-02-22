"""Probe the appliedTimeLimits and timeLimitOverrides:batchCreate endpoints.

Usage:
    python scripts/probe_time_limits.py <cookies_file>

Example:
    python scripts/probe_time_limits.py "C:/Users/Joche/Downloads/myaccount.google.com.cookies (5).json"
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import time
from urllib.parse import urlencode

import aiohttp

COOKIES_FILE = sys.argv[1] if len(sys.argv) > 1 else "cookies.json"

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
# Try both origins - the captured requests used families.google.com, but our
# working integration uses familylink.google.com
ORIGIN = "https://familylink.google.com"
ORIGIN_FAMILIES = "https://families.google.com"

# Captured static ext headers (protobuf blobs that don't change per-request)
# x-goog-ext-223261916-bin: client version / app identifier (contains "famlnk")
EXT_223261916 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
# x-goog-ext-202964622-bin: client/device metadata (session-stable)
EXT_202964622 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"


def load_cookies(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {c["name"]: c["value"] for c in raw}


def sapisid_hash(sapisid: str, origin: str) -> str:
    ts = str(int(time.time() * 1000))  # milliseconds, like the real client
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def make_headers(cookies: dict[str, str], origin: str = ORIGIN, content_type: str = "application/json+protobuf") -> dict[str, str]:
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
    return {
        "Authorization": sapisid_hash(sapisid, origin),
        "X-Goog-AuthUser": "0",
        "X-Goog-Api-Key": API_KEY,
        "Content-Type": content_type,
        "Origin": origin,
        "Referer": f"{origin}/",
        "x-goog-ext-223261916-bin": EXT_223261916,
        "x-goog-ext-202964622-bin": EXT_202964622,
    }


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items()
                     if not k.startswith("__Secure-OS"))


async def probe_applied_limits(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    child_id: str,
) -> None:
    url = f"{BASE}/people/{child_id}/appliedTimeLimits"
    params = {"capabilities": "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"}

    print(f"\n{'='*60}")
    print(f"GET appliedTimeLimits  child={child_id}")

    for origin in [ORIGIN, ORIGIN_FAMILIES]:
        headers = make_headers(cookies, origin)
        headers["Cookie"] = cookie_header(cookies)

        # without ext headers
        h_no_ext = {k: v for k, v in headers.items() if not k.startswith("x-goog-ext")}
        async with session.get(url, params=params, headers=h_no_ext) as r:
            body = await r.text()
            print(f"  [{origin}] no-ext → {r.status}")
            if r.status == 200:
                try:
                    print(json.dumps(json.loads(body), indent=2))
                except Exception:
                    print(body[:800])
            elif r.status not in (401, 403):
                print(f"  body: {body[:300]}")

        # with ext headers
        async with session.get(url, params=params, headers=headers) as r:
            body = await r.text()
            print(f"  [{origin}] with-ext → {r.status}")
            if r.status == 200:
                try:
                    print(json.dumps(json.loads(body), indent=2))
                except Exception:
                    print(body[:800])
            elif r.status not in (401, 403):
                print(f"  body: {body[:300]}")


async def probe_batch_create_dry(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    child_id: str,
    device_id: str,
) -> None:
    """Try different body formats for batchCreate (read-only probe: empty body first)."""
    url = f"{BASE}/people/{child_id}/timeLimitOverrides:batchCreate"

    print(f"\n{'='*60}")
    print(f"POST timeLimitOverrides:batchCreate  child={child_id} device={device_id}")

    # Try both origins
    for origin in [ORIGIN, ORIGIN_FAMILIES]:
        headers = make_headers(cookies, origin)
        headers["Cookie"] = cookie_header(cookies)

        # Attempt: empty body to see what error/schema hint we get
        async with session.post(url, json={}, headers=headers) as r:
            body = await r.text()
            if r.status not in (401, 403):
                print(f"\n  [{origin}] empty body → {r.status}")
                print(f"  {body[:600]}")
            else:
                print(f"  [{origin}] empty body → {r.status}")

        if True:  # always try all payloads
            for label, payload in [
                ("timeLimitOverrides[]", {"timeLimitOverrides": [{"deviceId": device_id, "dailyLimitInMs": 7200000}]}),
                ("requests[]", {"requests": [{"deviceId": device_id, "timeLimitOverride": {"dailyLimitInMs": 7200000}}]}),
                ("override{}", {"override": {"deviceId": device_id, "dailyLimitInMs": 7200000}}),
            ]:
                async with session.post(url, json=payload, headers=headers) as r:
                    body = await r.text()
                    if r.status not in (401, 403):
                        print(f"\n  [{origin}] {label} → {r.status}")
                        print(f"  {body[:600]}")


async def get_children(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
) -> list[dict]:
    url = f"{BASE}/families/mine/members"
    for origin in [ORIGIN, ORIGIN_FAMILIES]:
        sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")
        headers = {
            "Authorization": sapisid_hash(sapisid, origin),
            "X-Goog-AuthUser": "0",
            "X-Goog-Api-Key": API_KEY,
            "Origin": origin,
            "Referer": f"{origin}/",
            "Cookie": cookie_header(cookies),
        }
        async with session.get(url, headers=headers) as r:
            if r.status == 200:
                data = await r.json()
                children = []
                for m in data.get("members", []):
                    if m.get("role") == "ChildAccount":
                        child_id = m.get("profile", {}).get("obfuscatedGaiaId", "")
                        name = m.get("profile", {}).get("displayName", child_id)
                        devices = [d.get("deviceId", "") for d in m.get("childInfo", {}).get("deviceInfo", [])]
                        children.append({"child_id": child_id, "name": name, "devices": devices})
                        print(f"  Child: {name} ({child_id}) → devices: {devices}")
                return children
            else:
                print(f"  families/mine/members [{origin}]: {r.status}")

    # Fallback: use hardcoded child ID captured from browser DevTools
    print("  Using hardcoded child IDs from browser capture")
    return [
        {
            "name": "captured_child",
            "child_id": "112452138243419815198",
            # Known device IDs from previous probing:
            "devices": [
                "aannnppah2mzmppd2pzyvz555w3wbq4f4i2qd7qzrpiq",   # Emilio SM-X200
                "aannnppamndo3hpm5l75fc35uyf5efgsiibwjsaexvkq",   # Ronja VOG-L29
                "aannnppapjsjabgpoeqyqegjrlhxm44rghua23rzkacq",   # Ronja SM-X200
                "aannnppanqkemfw6nyffszirutt3aoyltrhqhkkvud3a",   # Lennard SM-X200
            ],
        }
    ]


async def main() -> None:
    cookies = load_cookies(COOKIES_FILE)
    print(f"Loaded {len(cookies)} cookies")

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        print("\n=== Fetching children & devices ===")
        children = await get_children(session, cookies)

        for child in children:
            cid = child["child_id"]
            await probe_applied_limits(session, cookies, cid)

            for dev_id in child["devices"][:2]:  # probe first 2 devices
                await probe_batch_create_dry(session, cookies, cid, dev_id)


if __name__ == "__main__":
    asyncio.run(main())
