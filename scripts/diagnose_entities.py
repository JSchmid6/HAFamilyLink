"""Diagnostic script: shows exactly what data the API returns and which entities would be created.

Usage:
    python scripts/diagnose_entities.py <path-to-cookies.json>
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

KIDSMANAGEMENT_BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
FAMILYLINK_ORIGIN = "https://familylink.google.com"
GOOG_API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
GOOG_EXT_BIN_223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
GOOG_EXT_BIN_202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

CAPABILITY_APP_USAGE = "CAPABILITY_APP_USAGE_SESSION"
CAPABILITY_SUPERVISION = "CAPABILITY_SUPERVISION_CAPABILITIES"
CAPABILITY_TIME_LIMITS = "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"


def _sapisidhash(sapisid: str, origin: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"{ts}_{digest}"


def _get_sapisid(cookies: list[dict]) -> str:
    for c in cookies:
        if c.get("name") == "SAPISID":
            return c["value"]
    for c in cookies:
        if c.get("name") in ("__Secure-3PAPISID", "APISID"):
            return c["value"]
    raise ValueError("SAPISID cookie not found!")


def _auth_headers(cookies: list[dict]) -> dict:
    sapisid = _get_sapisid(cookies)
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {
        "Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, FAMILYLINK_ORIGIN)}",
        "Origin": FAMILYLINK_ORIGIN,
        "X-Goog-Api-Key": GOOG_API_KEY,
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    }


async def run(cookie_file: str) -> None:
    cookies: list[dict] = json.loads(Path(cookie_file).read_text(encoding="utf-8"))
    print(f"✅ Loaded {len(cookies)} cookies\n")

    async with aiohttp.ClientSession() as session:

        # ── 1. Get family members ──────────────────────────────────────────────
        print("=" * 60)
        print("1. FAMILY MEMBERS")
        print("=" * 60)
        url = f"{KIDSMANAGEMENT_BASE_URL}/families/mine/members"
        async with session.get(url, headers=_auth_headers(cookies)) as resp:
            if resp.status != 200:
                print(f"❌ HTTP {resp.status} – check cookies!")
                return
            data = await resp.json(content_type=None)

        children = []
        for m in data.get("members", []):
            sup_info = m.get("memberSupervisionInfo", {})
            if sup_info.get("isSupervisedMember"):
                child = {
                    "child_id": m.get("userId", ""),
                    "name": m.get("profile", {}).get("displayName", "?"),
                }
                children.append(child)
                print(f"  👦 {child['name']} (id={child['child_id']})")

        if not children:
            print("❌ No supervised children found!")
            return

        for child in children:
            cid = child["child_id"]
            print(f"\n{'='*60}")
            print(f"2. APPS & USAGE for {child['name']}")
            print("=" * 60)

            url = f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/appsandusage"
            params = {"capabilities": [CAPABILITY_APP_USAGE, CAPABILITY_SUPERVISION]}
            async with session.get(url, headers=_auth_headers(cookies), params=params) as resp:
                status = resp.status
                raw = await resp.json(content_type=None)

            print(f"  HTTP {status}")
            apps = raw.get("apps", [])
            print(f"  Total apps in response: {len(apps)}")

            supervisable = []
            limited = []
            blocked = []
            for app in apps:
                title = app.get("title", app.get("packageName", "?"))
                caps = app.get("supervisionCapabilities", [])
                settings = app.get("supervisionSetting", {})
                can_limit = "capabilityUsageLimit" in caps
                is_blocked = settings.get("hidden", False)
                is_always_allowed = (
                    settings.get("alwaysAllowedAppInfo", {}).get("alwaysAllowedState")
                    == "alwaysAllowedStateEnabled"
                )
                if is_blocked:
                    blocked.append(title)
                elif settings.get("usageLimit"):
                    limited.append(title)
                if can_limit and not is_blocked and not is_always_allowed:
                    supervisable.append(title)

            print(f"  Apps with capabilityUsageLimit (supervisable): {len(supervisable)}")
            print(f"  Apps with active limit (limited): {len(limited)}")
            print(f"  Apps blocked: {len(blocked)}")
            if supervisable:
                print(f"  First 5 supervisable: {supervisable[:5]}")
            else:
                # Show first app's raw data to diagnose missing capability
                if apps:
                    sample = apps[0]
                    print(f"\n  ⚠️  supervisable is EMPTY! Sample app structure:")
                    print(f"    title: {sample.get('title', '?')}")
                    print(f"    supervisionCapabilities: {sample.get('supervisionCapabilities', 'MISSING')}")
                    print(f"    supervisionSetting keys: {list(sample.get('supervisionSetting', {}).keys())}")

            # ── 3. Applied time limits (devices) ──────────────────────────────
            print(f"\n{'='*60}")
            print(f"3. APPLIED TIME LIMITS (devices) for {child['name']}")
            print("=" * 60)
            url = f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/appliedTimeLimits"
            params2 = {"capabilities": [CAPABILITY_TIME_LIMITS]}
            async with session.get(url, headers={
                **_auth_headers(cookies),
                "Content-Type": "application/json",
            }, params=params2) as resp:
                status = resp.status
                atl_raw = await resp.json(content_type=None)
            print(f"  HTTP {status}")
            devices = atl_raw.get("appliedTimeLimits", [])
            print(f"  Devices found: {len(devices)}")
            for dev in devices:
                did = dev.get("deviceId", "?")
                usage_ms = int(dev.get("currentUsageUsedMillis", 0) or 0)
                print(f"    📱 {did[-8:]}  usage={usage_ms//60000}min  locked={dev.get('isLocked')}")
                # This tells us DeviceBonusTimeNumber and DeviceScreenTimeSensor would be created
            if not devices:
                print("  ⚠️  No devices – DeviceBonusTimeNumber + DeviceScreenTimeSensor won't be created!")

            # ── 4. Daily time limits ───────────────────────────────────────────
            print(f"\n{'='*60}")
            print(f"4. DAILY TIME LIMITS (timeLimit) for {child['name']}")
            print("=" * 60)
            url = f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/timeLimit"
            tl_headers = {
                **_auth_headers(cookies),
                "Content-Type": "application/json+protobuf",
                "x-goog-ext-223261916-bin": GOOG_EXT_BIN_223,
                "x-goog-ext-202964622-bin": GOOG_EXT_BIN_202,
            }
            async with session.get(url, headers=tl_headers) as resp:
                status = resp.status
                tl_raw = await resp.text()
            print(f"  HTTP {status}")
            if status == 200:
                try:
                    tl_data = json.loads(tl_raw)
                    entries = tl_data[1][1][0][2]
                    day_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
                    print(f"  Daily limits found: {len(entries)}")
                    for entry in entries:
                        eid, day, _, quota = entry[0], entry[1], entry[2], entry[3]
                        print(f"    {day_names.get(day, day)}: {quota} min  (entry_id={eid})")
                except Exception as e:
                    print(f"  ⚠️  Parse error: {e}")
                    print(f"  Raw (first 200 chars): {tl_raw[:200]}")
            else:
                print(f"  ⚠️  Failed – no DeviceDailyLimitNumber entities!")

        print(f"\n{'='*60}")
        print("SUMMARY – which HA entities would be created:")
        print("=" * 60)
        print(f"  ChildSupervisionSwitch (switch): {len(children)} ✅ (if supervisor data fetched)")
        print(f"  ChildScreenTimeSensor (sensor): {len(children)} ✅")
        print(f"  DeviceScreenTimeSensor (sensor): depends on devices count above")
        print(f"  AppTimeLimitNumber (number): depends on supervisable count above")
        print(f"  DeviceBonusTimeNumber (number): depends on devices count above")
        print(f"  DeviceDailyLimitNumber (number): 7 per child if timeLimit succeeds")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path-to-cookies.json>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
