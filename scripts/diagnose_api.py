"""Standalone API diagnostic script for HAFamilyLink.

Runs the real Google Kids Management API calls using a cookies JSON file,
without needing a running Home Assistant instance.

Optionally saves raw API responses as a timestamped snapshot that can later
be compared in a subsequent --compare run to detect API format changes.

Usage:
    python scripts/diagnose_api.py <cookies.json> [--save] [--compare <snapshot-dir>]

Examples:
    # Basic run
    python scripts/diagnose_api.py "C:/Users/Joche/Downloads/familylink.google.com.cookies (4).json"

    # Save snapshot for future comparison
    python scripts/diagnose_api.py cookies.json --save

    # Compare live responses against a previous snapshot to detect API changes
    python scripts/diagnose_api.py cookies.json --compare scripts/snapshots/2026-02-20_14-30-00
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Add project root to sys.path so we can import the integration's parsers
# ---------------------------------------------------------------------------
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

import aiohttp  # noqa: E402

# ---------------------------------------------------------------------------
# Constants (mirrored from const.py)
# ---------------------------------------------------------------------------
KIDSMANAGEMENT_BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
FAMILYLINK_ORIGIN = "https://familylink.google.com"
CAPABILITY_TIME_LIMITS = "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"
GOOG_API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0"
)
SEP = "─" * 70

# ---------------------------------------------------------------------------
# Expected field schemas – used to detect API changes automatically.
# When Google changes the response format, these checks catch it immediately.
# ---------------------------------------------------------------------------
EXPECTED_SCHEMAS: dict[str, dict] = {
    "appliedTimeLimits": {
        "description": "Per-device screen time state",
        "dict_key": "appliedTimeLimits",
        "entry_fields": {
            "deviceId":               "str – opaque device ID",
            "isLocked":               "bool – device locked state",
            "activePolicy":           "str – e.g. noActivePolicy / usageLimit",
            "currentUsageUsedMillis": "str – milliseconds of screen time used today",
            "currentUsageLimitEntry": "dict → usageQuotaMins:int",
        },
    },
    "devices": {
        "description": "Physical device registry",
        "dict_key": "devices",
        "entry_fields": {
            "deviceId":    "str – opaque device ID",
            "displayInfo": "dict → friendlyName/model",
        },
    },
    "timeLimit": {
        "description": "Persistent weekly schedule",
        "dict_key": "timeLimit",
        "entry_fields": {
            "deviceId":          "str",
            "dailyLimitEntries": "list → usageQuotaMins per day",
        },
    },
    "members": {
        "description": "Family members",
        "dict_key": "members",
        "entry_fields": {
            "userId":                "str – child user ID",
            "profile":               "dict → displayName",
            "memberSupervisionInfo": "dict → isSupervisedMember",
        },
    },
}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _sapisidhash(sapisid: str, origin: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"{ts}_{digest}"


def _build_cookies(cookie_list: list[dict]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookie_list}


def _auth_headers(cookies: dict[str, str]) -> dict[str, str]:
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID", "")
    if not sapisid:
        print("  ⚠  WARNING: No SAPISID cookie – auth will fail")
    # Cookies are injected as an explicit header (same as the integration).
    # aiohttp's CookieJar does domain/secure filtering that drops google.com cookies
    # when calling kidsmanagement-pa.clients6.google.com, so we bypass it.
    return {
        "Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, FAMILYLINK_ORIGIN)}",
        "Origin": FAMILYLINK_ORIGIN,
        "X-Goog-Api-Key": GOOG_API_KEY,
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_schema(endpoint_key: str, raw: Any) -> list[str]:
    """Check raw response against expected schema. Returns list of warnings."""
    schema = EXPECTED_SCHEMAS.get(endpoint_key)
    if not schema:
        return []

    warnings: list[str] = []
    top_key = schema["dict_key"]

    if not isinstance(raw, dict):
        warnings.append(
            f"Response is {type(raw).__name__}, expected dict with '{top_key}' key"
        )
        return warnings

    if top_key not in raw:
        warnings.append(
            f"Top-level key '{top_key}' MISSING. Keys present: {list(raw.keys())}"
        )
        return warnings

    entries = raw[top_key]
    if not isinstance(entries, list):
        warnings.append(f"'{top_key}' is {type(entries).__name__}, expected list")
        return warnings
    if not entries:
        warnings.append(f"'{top_key}' list is empty")
        return warnings

    first = entries[0]
    if not isinstance(first, dict):
        warnings.append(f"Entries are {type(first).__name__}, expected dict")
        return warnings

    for field, desc in schema["entry_fields"].items():
        if field not in first:
            warnings.append(f"Field '{field}' ({desc})  ← MISSING")

    # Report fields we're not yet using (may be useful new data)
    known = set(schema["entry_fields"].keys()) | {"apiHeader"}
    new_fields = set(first.keys()) - known
    if new_fields:
        warnings.append(f"New/unused fields in entry: {sorted(new_fields)}")

    return warnings


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def save_snapshot(data: dict[str, Any], snapshot_dir: Path) -> None:
    """Write each endpoint's raw response to a separate JSON file."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for name, content in data.items():
        path = snapshot_dir / f"{name}.json"
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = {
        "timestamp": datetime.datetime.now().isoformat(),
        "endpoints": list(data.keys()),
    }
    (snapshot_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\n  ✓ Snapshot saved → {snapshot_dir}")


def compare_snapshots(old_dir: Path, new_data: dict[str, Any]) -> None:
    """Compare live responses against a saved snapshot, printing structural diffs."""
    print(f"\n{SEP}")
    print(f"  SNAPSHOT COMPARISON  (baseline: {old_dir.name})")
    print(SEP)

    for name, new_raw in new_data.items():
        old_file = old_dir / f"{name}.json"
        if not old_file.exists():
            print(f"\n  [{name}]  NEW endpoint (not in baseline)")
            continue
        old_raw = json.loads(old_file.read_text(encoding="utf-8"))
        changes = _diff_structure(old_raw, new_raw, path=name)
        if changes:
            print(f"\n  ⚠  [{name}]  STRUCTURE CHANGED:")
            for c in changes:
                print(f"       {c}")
        else:
            print(f"  ✓  [{name}]  unchanged")


def _diff_structure(old: Any, new: Any, path: str = "", depth: int = 0) -> list[str]:
    """Recursively compare key/field structure (not values). Returns change descriptions."""
    diffs: list[str] = []
    if type(old) != type(new):
        diffs.append(f"{path}: type  {type(old).__name__} → {type(new).__name__}")
        return diffs

    if isinstance(old, dict):
        old_keys, new_keys = set(old.keys()), set(new.keys())
        for k in sorted(old_keys - new_keys):
            diffs.append(f"{path}.{k}  KEY REMOVED")
        for k in sorted(new_keys - old_keys):
            if depth < 2:
                diffs.append(f"{path}.{k}  KEY ADDED")
        if depth < 3:
            for k in old_keys & new_keys:
                diffs.extend(_diff_structure(old[k], new[k], f"{path}.{k}", depth + 1))

    elif isinstance(old, list) and old and new:
        diffs.extend(_diff_structure(old[0], new[0], f"{path}[0]", depth + 1))

    return diffs


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

async def _get_json(
    session: aiohttp.ClientSession,
    cookies: dict[str, str],
    url: str,
    params: dict | None = None,
) -> Any:
    headers = {"Content-Type": "application/json", **_auth_headers(cookies)}
    async with session.get(url, headers=headers, params=params) as resp:
        short = url.replace(KIDSMANAGEMENT_BASE_URL, "")
        print(f"  GET {short}  →  HTTP {resp.status}")
        resp.raise_for_status()
        return await resp.json(content_type=None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(cookies_path: str, save: bool, compare_dir: str | None) -> None:
    print(SEP)
    print("  HAFamilyLink API Diagnostic")
    print(f"  Cookies: {cookies_path}")
    if save:
        print("  Mode: LIVE + SAVE SNAPSHOT")
    if compare_dir:
        print(f"  Baseline: {compare_dir}")
    print(SEP)

    try:
        cookie_list = json.loads(Path(cookies_path).read_text(encoding="utf-8"))
        cookies = _build_cookies(cookie_list)
        print(f"\n✓ Loaded {len(cookie_list)} cookies")
        missing = [n for n in ("SAPISID", "SID", "__Secure-1PSID") if n not in cookies]
        if missing:
            print(f"  ⚠  Missing critical cookies: {missing}")
    except Exception as e:
        print(f"\n✗ Failed to load cookies: {e}")
        return

    snapshot: dict[str, Any] = {}

    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        headers={"User-Agent": _USER_AGENT},
    ) as session:

        # ── Step 1: Members ─────────────────────────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 1: /families/mine/members")
        print(SEP)
        try:
            raw = await _get_json(
                session, cookies,
                f"{KIDSMANAGEMENT_BASE_URL}/families/mine/members",
            )
            snapshot["members"] = raw
            _print_schema_check("members", raw)

            children = [
                {
                    "child_id": m.get("userId", ""),
                    "name": m.get("profile", {}).get("displayName", ""),
                }
                for m in raw.get("members", [])
                if m.get("memberSupervisionInfo", {}).get("isSupervisedMember", False)
            ]
            if not children:
                print("  ✗ No supervised children found!")
                return
            for c in children:
                print(f"  ✓ {c['name']}  ({c['child_id']})")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return

        from custom_components.familylink.client.parsers import parse_applied_time_limits

        # ── Step 2: appliedTimeLimits ────────────────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 2: /people/{id}/appliedTimeLimits  (screen time + device state)")
        print(SEP)
        for child in children:
            cid, cname = child["child_id"], child["name"]
            print(f"\n  ── {cname} ──")
            try:
                raw = await _get_json(
                    session, cookies,
                    f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/appliedTimeLimits",
                    params={"capabilities": CAPABILITY_TIME_LIMITS},
                )
                snapshot[f"appliedTimeLimits_{cid}"] = raw
                _print_schema_check("appliedTimeLimits", raw)

                parsed = parse_applied_time_limits(raw)
                print(f"  Parser → {len(parsed)} device(s)")
                for dev in parsed:
                    lock = "🔒" if dev["is_locked"] else "🔓"
                    print(f"    {lock} {dev['device_id']}")
                    print(f"       usage today  = {dev['usage_minutes_today']} min")
                    print(f"       quota today  = {dev['today_limit_minutes']} min")
                    print(f"       policy       = {dev['active_policy']}")
            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

        # ── Step 3: /devices ────────────────────────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 3: /people/{id}/devices  (device names)")
        print(SEP)
        for child in children:
            cid, cname = child["child_id"], child["name"]
            print(f"\n  ── {cname} ──")
            try:
                raw = await _get_json(
                    session, cookies,
                    f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/devices",
                )
                snapshot[f"devices_{cid}"] = raw
                _print_schema_check("devices", raw)

                if isinstance(raw, dict):
                    for dev in raw.get("devices", []):
                        did = dev.get("deviceId", "?")
                        display = dev.get("displayInfo", {})
                        name = (
                            display.get("friendlyName")
                            or display.get("model")
                            or "?"
                        )
                        print(f"    ✓ {name}  ({did})")
            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

        # ── Step 4: timeLimit (weekly schedule) ─────────────────────────────
        print(f"\n{SEP}")
        print("  STEP 4: /people/{id}/timeLimit  (persistent weekly schedule)")
        print(SEP)
        for child in children:
            cid, cname = child["child_id"], child["name"]
            print(f"\n  ── {cname} ──")
            try:
                raw = await _get_json(
                    session, cookies,
                    f"{KIDSMANAGEMENT_BASE_URL}/people/{cid}/timeLimit",
                )
                snapshot[f"timeLimit_{cid}"] = raw
                _print_schema_check("timeLimit", raw)

                if isinstance(raw, dict):
                    limits = raw.get("timeLimit", raw.get("timeLimits", []))
                    if isinstance(limits, list):
                        for entry in limits:
                            did = entry.get("deviceId", "?")
                            daily = entry.get("dailyLimitEntries", [])
                            quotas = [
                                f"{e.get('effectiveDay','?')}={e.get('usageQuotaMins','?')}min"
                                for e in (daily if isinstance(daily, list) else [])
                            ]
                            print(f"    device {did[-12:]}: {', '.join(quotas[:4])}{'…' if len(quotas)>4 else ''}")
                    else:
                        print(f"    Unexpected structure – top-level keys: {list(raw.keys())}")
            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")

    # ── Snapshot compare / save ──────────────────────────────────────────────
    if compare_dir:
        compare_snapshots(Path(compare_dir), snapshot)

    if save:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        snap_dir = _root / "scripts" / "snapshots" / ts
        save_snapshot(snapshot, snap_dir)
        print(f"  Next run: --compare scripts/snapshots/{ts}")

    print(f"\n{SEP}")
    print("  Done.")
    print(SEP)


def _print_schema_check(endpoint_key: str, raw: Any) -> None:
    warnings = validate_schema(endpoint_key, raw)
    if warnings:
        for w in warnings:
            print(f"  ⚠  SCHEMA: {w}")
    else:
        schema = EXPECTED_SCHEMAS.get(endpoint_key, {})
        print(f"  ✓ Schema OK ({schema.get('description', endpoint_key)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAFamilyLink API diagnostic tool")
    parser.add_argument("cookies", help="Path to exported cookies JSON file")
    parser.add_argument(
        "--save", action="store_true",
        help="Save raw API responses as a timestamped snapshot in scripts/snapshots/",
    )
    parser.add_argument(
        "--compare", metavar="SNAPSHOT_DIR",
        help="Compare current live responses against a previously saved snapshot",
    )
    args = parser.parse_args()
    asyncio.run(main(args.cookies, args.save, args.compare))

