"""Analyze a HAR (HTTP Archive) file exported from browser DevTools.

Finds all Family Link API calls, validates their response format against the
expected schema, and runs the integration's parsers on them. Use this to
detect API format changes without deploying to Home Assistant.

Export a HAR file:
  Chrome:  DevTools (F12) → Network → right-click any request
           → "Save all as HAR with content"
  Firefox: DevTools (F12) → Network → right-click any request
           → "Save All as HAR"

Usage:
    python scripts/analyze_har.py <file.har>
    python scripts/analyze_har.py <file.har> --save
    python scripts/analyze_har.py <file.har> --compare scripts/snapshots/2026-02-20_14-30-00
    python scripts/analyze_har.py <file.har> --raw-limit 500
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Shared schema definitions and helpers from diagnose_api
# ---------------------------------------------------------------------------
_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))

# We re-use EXPECTED_SCHEMAS, validate_schema, save_snapshot, compare_snapshots,
# and _diff_structure from diagnose_api.py rather than duplicating them.
from scripts.diagnose_api import (  # noqa: E402
    EXPECTED_SCHEMAS,
    SEP,
    _diff_structure,
    _print_schema_check,
    compare_snapshots,
    save_snapshot,
    validate_schema,
)

# ---------------------------------------------------------------------------
# Endpoint identification
# ---------------------------------------------------------------------------

KIDSMANAGEMENT_HOST = "kidsmanagement-pa.clients6.google.com"

# Maps URL path fragments → schema key used in EXPECTED_SCHEMAS
_ENDPOINT_MAP: dict[str, str] = {
    "appliedTimeLimits": "appliedTimeLimits",
    "timeLimit":         "timeLimit",
    "devices":           "devices",
    "members":           "members",
}


def _identify_endpoint(url: str) -> str | None:
    """Return the schema key if the URL matches a known Family Link endpoint."""
    path = urlparse(url).path  # e.g. /kidsmanagement/v1/people/xxx/appliedTimeLimits
    for fragment, key in _ENDPOINT_MAP.items():
        if path.endswith(f"/{fragment}") or f"/{fragment}?" in url:
            return key
    return None


def _child_id_from_url(url: str) -> str:
    """Extract the child user-id from a /people/{id}/... URL path."""
    parts = urlparse(url).path.split("/")
    try:
        idx = parts.index("people")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return "unknown"


def _decode_response_body(entry: dict) -> str | None:
    """Return the response body text from a HAR entry (handles base64 encoding)."""
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not text:
        return None
    encoding = content.get("encoding", "")
    if encoding == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return text
    return text


# ---------------------------------------------------------------------------
# HAR analysis
# ---------------------------------------------------------------------------

def analyze_har(
    har_path: Path,
    raw_limit: int,
    save: bool,
    compare_dir: str | None,
) -> None:
    print(SEP)
    print(f"  HAFamilyLink HAR Analyzer")
    print(f"  File: {har_path.name}")
    print(SEP)

    try:
        har = json.loads(har_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"\n✗ Failed to read HAR file: {e}")
        sys.exit(1)

    entries: list[dict] = har.get("log", {}).get("entries", [])
    print(f"\n✓ HAR loaded — {len(entries)} total network entries")

    # Filter to Family Link API calls only
    fl_entries = [
        e for e in entries
        if KIDSMANAGEMENT_HOST in e.get("request", {}).get("url", "")
    ]
    if not fl_entries:
        print(f"\n✗ No requests to {KIDSMANAGEMENT_HOST} found in HAR.")
        print("  Make sure you captured HAR while the Family Link page was open.")
        return

    print(f"  Found {len(fl_entries)} Family Link API request(s)\n")

    snapshot: dict[str, Any] = {}

    # Try importing parsers (optional – shows parser output when available)
    try:
        from custom_components.familylink.client.parsers import parse_applied_time_limits as _parse_atl
        _parsers_available = True
    except ImportError:
        _parse_atl = None
        _parsers_available = False
        print("  ⚠  Integration parsers not importable (run from project root)")

    for i, entry in enumerate(fl_entries, start=1):
        req = entry.get("request", {})
        resp = entry.get("response", {})
        url = req.get("url", "")
        status = resp.get("status", "?")
        method = req.get("method", "GET")
        endpoint_key = _identify_endpoint(url)
        cid = _child_id_from_url(url) if "/people/" in url else "family"

        short_url = url.split(KIDSMANAGEMENT_HOST)[-1].split("?")[0]
        print(f"{SEP}")
        print(f"  [{i}/{len(fl_entries)}]  {method} {short_url}  →  HTTP {status}")
        if "/people/" in url:
            print(f"  Child ID: {cid}")

        body_text = _decode_response_body(entry)
        if not body_text:
            print("  ⚠  Empty response body")
            continue

        if status != 200:
            print(f"  ⚠  Non-200 response — skipping parse")
            if raw_limit > 0:
                print(f"  RAW (first {raw_limit} chars): {body_text[:raw_limit]}")
            continue

        try:
            raw: Any = json.loads(body_text)
        except json.JSONDecodeError as exc:
            print(f"  ✗ Response is not JSON: {exc}")
            if raw_limit > 0:
                print(f"  RAW (first {raw_limit} chars): {body_text[:raw_limit]}")
            continue

        resp_type = type(raw).__name__
        if isinstance(raw, dict):
            print(f"  Format: JSON dict — keys: {list(raw.keys())}")
        elif isinstance(raw, list):
            print(f"  Format: JSON list — length {len(raw)}")
        else:
            print(f"  Format: {resp_type}")

        # Schema validation
        if endpoint_key:
            _print_schema_check(endpoint_key, raw)
        else:
            print("  Schema: (unknown endpoint – no schema defined)")

        # Run parser output where available
        if _parsers_available and endpoint_key == "appliedTimeLimits":
            try:
                parsed = _parse_atl(raw)
                print(f"  Parser → {len(parsed)} device(s)")
                for dev in parsed:
                    lock = "🔒" if dev["is_locked"] else "🔓"
                    print(f"    {lock} {dev['device_id']}  usage={dev['usage_minutes_today']}min  "
                          f"quota={dev['today_limit_minutes']}min  policy={dev['active_policy']}")
            except Exception as exc:
                print(f"  ✗ Parser error: {exc}")

        # Collect for snapshot
        snap_key = f"{endpoint_key or short_url.strip('/')}_{cid}"
        snapshot[snap_key] = raw

        if raw_limit > 0:
            raw_str = json.dumps(raw, indent=2, ensure_ascii=False)
            if len(raw_str) > raw_limit:
                raw_str = raw_str[:raw_limit] + f"\n  … (truncated at {raw_limit} chars)"
            print(f"\n  RAW:\n{raw_str}")

    print(f"\n{SEP}")
    print(f"  Summary: {len(fl_entries)} endpoint call(s) analyzed")

    if compare_dir:
        compare_snapshots(Path(compare_dir), snapshot)

    if save and snapshot:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        snap_dir = _root / "scripts" / "snapshots" / ts
        save_snapshot(snapshot, snap_dir)
        print(f"  Next run: --compare scripts/snapshots/{ts}")

    print(SEP)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze Family Link API calls captured in a HAR file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/analyze_har.py network.har\n"
            "  python scripts/analyze_har.py network.har --save\n"
            "  python scripts/analyze_har.py network.har --compare scripts/snapshots/2026-02-20_14-30-00\n"
            "  python scripts/analyze_har.py network.har --raw-limit 0  # suppress raw output\n"
        ),
    )
    parser.add_argument("har_file", help="Path to the .har file exported from DevTools")
    parser.add_argument(
        "--save", action="store_true",
        help="Save parsed responses as a timestamped snapshot in scripts/snapshots/",
    )
    parser.add_argument(
        "--compare", metavar="SNAPSHOT_DIR",
        help="Compare responses against a previously saved snapshot directory",
    )
    parser.add_argument(
        "--raw-limit", type=int, default=1200, metavar="N",
        help="Max chars of raw JSON to print per response (default: 1200, 0=off)",
    )
    args = parser.parse_args()

    har_path = Path(args.har_file)
    if not har_path.exists():
        print(f"✗ File not found: {har_path}")
        sys.exit(1)

    analyze_har(har_path, args.raw_limit, args.save, args.compare)
