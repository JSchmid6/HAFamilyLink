"""Standalone API diagnostic script for HAFamilyLink.

Runs the real Google Kids Management API calls using a cookies JSON file,
without needing a running Home Assistant instance.

Usage:
    python scripts/diagnose_api.py path/to/cookies.json

Example:
    python scripts/diagnose_api.py "C:/Users/Joche/Downloads/familylink.google.com.cookies (4).json"
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Add project root to sys.path so we can import the integration's parsers
# ---------------------------------------------------------------------------
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

import aiohttp  # noqa: E402


# ---------------------------------------------------------------------------
# Constants (copied from const.py to keep script standalone)
# ---------------------------------------------------------------------------
KIDSMANAGEMENT_BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
FAMILYLINK_ORIGIN = "https://familylink.google.com"
CAPABILITY_APP_USAGE = "CAPABILITY_APP_USAGE_SESSION"
CAPABILITY_SUPERVISION = "CAPABILITY_SUPERVISION_CAPABILITIES"
CAPABILITY_TIME_LIMITS = "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
GOOG_API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0"
)

SEP = "─" * 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sapisidhash(sapisid: str, origin: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"{ts}_{digest}"


def _build_cookies(cookie_list: list[dict]) -> dict[str, str]:
    """Convert the JSON cookie list to a name→value dict."""
    return {c["name"]: c["value"] for c in cookie_list}


def _auth_headers(cookies: dict[str, str]) -> dict[str, str]:
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID", "")
    if not sapisid:
        print("  ⚠  WARNING: No SAPISID or __Secure-1PAPISID cookie found – auth will fail")
    # Cookies are injected as an explicit Cookie header (same as the integration).
    # aiohttp's CookieJar does domain/secure checks that filter out subdomain cookies,
    # so we bypass it entirely and set the header manually.
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, FAMILYLINK_ORIGIN)}",
        "Origin": FAMILYLINK_ORIGIN,
        "X-Goog-Api-Key": GOOG_API_KEY,
        "Cookie": cookie_header,
    }


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

async def get_members(session: aiohttp.ClientSession, cookies: dict[str, str]) -> list[dict]:
    url = f"{KIDSMANAGEMENT_BASE_URL}/families/mine/members"
    headers = {"Content-Type": "application/json", **_auth_headers(cookies)}
    async with session.get(url, headers=headers) as resp:
        print(f"  GET /families/mine/members  →  HTTP {resp.status}")
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    members = []
    for m in data.get("members", []):
        sup = m.get("memberSupervisionInfo", {})
        if not sup.get("isSupervisedMember", False):
            continue
        profile = m.get("profile", {})
        members.append({
            "child_id": m.get("userId", ""),
            "name": profile.get("displayName", ""),
            "email": profile.get("email", ""),
        })
    return members


async def get_applied_time_limits_raw(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    child_id: str,
) -> object:
    url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/appliedTimeLimits"
    headers = {"Content-Type": "application/json", **_auth_headers(cookies)}
    params = {"capabilities": CAPABILITY_TIME_LIMITS}
    async with session.get(url, headers=headers, params=params) as resp:
        print(f"  GET /people/{child_id}/appliedTimeLimits  →  HTTP {resp.status}")
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def get_devices_raw(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    child_id: str,
) -> object:
    url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/devices"
    headers = {"Content-Type": "application/json", **_auth_headers(cookies)}
    async with session.get(url, headers=headers) as resp:
        print(f"  GET /people/{child_id}/devices  →  HTTP {resp.status}")
        resp.raise_for_status()
        return await resp.json(content_type=None)


# ---------------------------------------------------------------------------
# Main diagnostic logic
# ---------------------------------------------------------------------------

async def main(cookies_path: str) -> None:
    print(SEP)
    print(f"  HAFamilyLink API Diagnostic")
    print(f"  Cookies: {cookies_path}")
    print(SEP)

    # Load cookies
    try:
        cookie_list: list[dict] = json.loads(Path(cookies_path).read_text(encoding="utf-8"))
        cookies = _build_cookies(cookie_list)
        print(f"\n✓ Loaded {len(cookie_list)} cookies")
        print(f"  Present: {', '.join(sorted(cookies.keys()))}")
    except Exception as e:
        print(f"\n✗ Failed to load cookies: {e}")
        return

    # Check critical cookies
    missing = [n for n in ("SAPISID", "SID", "__Secure-1PSID") if n not in cookies]
    if missing:
        print(f"\n  ⚠  WARNING: Missing cookies: {missing}")

    cookie_jar = aiohttp.CookieJar()
    async with aiohttp.ClientSession(
        cookie_jar=cookie_jar,
        headers={"User-Agent": _USER_AGENT},
    ) as session:

        # ── Step 1: Get children ────────────────────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 1: Get supervised children")
        print(SEP)
        try:
            children = await get_members(session, cookies)
            if not children:
                print("  ✗ No supervised children found! Check cookies/account.")
                return
            for c in children:
                print(f"  ✓ Child: {c['name']} ({c['child_id']})")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return

        # ── Step 2: appliedTimeLimits per child ─────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 2: appliedTimeLimits (physical devices)")
        print(SEP)
        for child in children:
            cid = child["child_id"]
            cname = child["name"]
            print(f"\n  Child: {cname} ({cid})")
            try:
                raw = await get_applied_time_limits_raw(session, cookies, cid)

                print(f"\n  RAW RESPONSE (type={type(raw).__name__}):")
                print(f"  {json.dumps(raw, indent=2)[:2000]}")  # cap at 2000 chars

                # Now run the parser
                from custom_components.familylink.client.parsers import parse_applied_time_limits
                parsed = parse_applied_time_limits(raw)
                print(f"\n  PARSED: {len(parsed)} device(s)")
                for dev in parsed:
                    print(f"    device_id={dev['device_id']}")
                    print(f"    usage_minutes_today={dev['usage_minutes_today']}")
                    print(f"    today_limit_minutes={dev['today_limit_minutes']}")
                    print(f"    is_locked={dev['is_locked']}")

                if not parsed and isinstance(raw, list) and len(raw) >= 2:
                    entries = raw[1]
                    if isinstance(entries, list) and entries:
                        first = entries[0]
                        print(f"\n  ⚠  Parser got 0 devices but raw[1] has {len(entries)} entries!")
                        print(f"  ⚠  First raw entry has {len(first) if isinstance(first, list) else '?'} fields")
                        if isinstance(first, list):
                            for i, val in enumerate(first):
                                if val is not None and val != [] and val != "":
                                    print(f"       index[{i:2d}] = {repr(val)[:120]}")

            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

		# ── Step 3: /devices per child ──────────────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 3: /devices (device names)")
        print(SEP)
        for child in children:
            cid = child["child_id"]
            cname = child["name"]
            print(f"\n  Child: {cname} ({cid})")
            try:
                raw = await get_devices_raw(session, cookies, cid)
                # New JSON-dict format
                if isinstance(raw, dict):
                    for device in raw.get("devices", []):
                        did = device.get("deviceId", "?")
                        display = device.get("displayInfo", {})
                        name = display.get("friendlyName") or display.get("model") or "?"
                        print(f"    device_id={did}  name={name!r}")
                # Legacy JSPB format
                elif isinstance(raw, list) and len(raw) >= 2 and isinstance(raw[1], list):
                    for entry in raw[1]:
                        if not isinstance(entry, list) or len(entry) < 11:
                            continue
                        dev_id = entry[0] if isinstance(entry[0], str) else "?"
                        name_10 = entry[10] if len(entry) > 10 else "<missing>"
                        print(f"    device_id={dev_id}  name(idx10)={name_10!r}")
                else:
                    print(f"  Unexpected format: {type(raw).__name__}: {json.dumps(raw)[:300]}")

            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

    print(f"\n{SEP}")
    print("  Done.")
    print(SEP)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_api.py <path-to-cookies.json>")
        print()
        print("Example:")
        print('  python scripts/diagnose_api.py "C:/Users/Joche/Downloads/familylink.google.com.cookies (4).json"')
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
