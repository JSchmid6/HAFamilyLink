"""Explore the full Google Family Link API response to find overall screen time endpoint.

Usage: .venv/Scripts/python.exe scripts/explore_api.py <cookie_file>
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
ORIGIN = "https://familylink.google.com"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"


def sapisidhash(sapisid: str) -> str:
    ts = int(time.time() * 1000)
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"{ts}_{digest}"


def load_cookies(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_sapisid(cookies: list[dict]) -> str:
    for c in cookies:
        if c["name"] == "SAPISID" and ".google.com" in c.get("domain", ""):
            return c["value"]
    for c in cookies:
        if c["name"] in ("__Secure-3PAPISID", "APISID"):
            return c["value"]
    raise ValueError("SAPISID not found")


def make_headers(cookies: list[dict]) -> dict:
    sapisid = get_sapisid(cookies)
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return {
        "Authorization": f"SAPISIDHASH {sapisidhash(sapisid)}",
        "Origin": ORIGIN,
        "X-Goog-Api-Key": API_KEY,
        "Cookie": cookie_str,
        "User-Agent": USER_AGENT,
    }


def main():
    cookie_file = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Joche\Downloads\myaccount.google.com.cookies (4).json"
    cookies = load_cookies(cookie_file)
    headers = make_headers(cookies)

    with httpx.Client(headers=headers, timeout=30) as client:
        # Step 1: Get members
        print("=== GET /families/mine/members ===")
        r = client.get(
            f"{BASE_URL}/families/mine/members",
            headers={"Content-Type": "application/json"},
        )
        print(f"HTTP {r.status_code}")
        members_data = r.json()
        children = []
        for m in members_data.get("members", []):
            sup = m.get("memberSupervisionInfo", {})
            if sup.get("isSupervisedMember"):
                child_id = m["userId"]
                name = m.get("profile", {}).get("displayName", "?")
                children.append((child_id, name))
                print(f"  Child: {name} ({child_id})")
        print()

        for child_id, name in children[:1]:  # test with first child only
            print(f"=== GET /people/{child_id}/appsandusage (raw, truncated at 5000 chars) ===")
            r = client.get(
                f"{BASE_URL}/people/{child_id}/appsandusage",
                headers={"Content-Type": "application/json"},
                params={
                    "capabilities": [
                        "CAPABILITY_APP_USAGE_SESSION",
                        "CAPABILITY_SUPERVISION_CAPABILITIES",
                    ]
                },
            )
            print(f"HTTP {r.status_code}")
            data = r.json()
            raw = json.dumps(data, indent=2, ensure_ascii=False)
            print(raw[:5000])
            print("... (truncated)" if len(raw) > 5000 else "")
            print()

            # More capabilities variants
            all_caps = [
                "CAPABILITY_APP_USAGE_SESSION",
                "CAPABILITY_SUPERVISION_CAPABILITIES",
                "CAPABILITY_DEVICE_RESTRICTIONS",
                "CAPABILITY_SCREEN_TIME",
            ]
            print(f"=== GET /people/{child_id}/appsandusage (all capabilities) ===")
            r2 = client.get(
                f"{BASE_URL}/people/{child_id}/appsandusage",
                headers={"Content-Type": "application/json"},
                params={"capabilities": all_caps},
            )
            print(f"HTTP {r2.status_code}")
            if r2.status_code == 200:
                data2 = r2.json()
                # Show keys in top level
                print("Top-level keys:", list(data2.keys()))
            print()

            # Try supervisionSettings endpoint
            print(f"=== GET /people/{child_id}/supervisionSettings ===")
            r3 = client.get(
                f"{BASE_URL}/people/{child_id}/supervisionSettings",
                headers={"Content-Type": "application/json"},
            )
            print(f"HTTP {r3.status_code}")
            if r3.status_code == 200:
                print(json.dumps(r3.json(), indent=2, ensure_ascii=False)[:3000])
            else:
                print(r3.text[:500])
            print()

            # Try capabilities endpoint
            print(f"=== GET /people/{child_id}/capabilities ===")
            r4 = client.get(
                f"{BASE_URL}/people/{child_id}/capabilities",
                headers={"Content-Type": "application/json"},
            )
            print(f"HTTP {r4.status_code}")
            if r4.status_code == 200:
                print(json.dumps(r4.json(), indent=2, ensure_ascii=False)[:3000])
            else:
                print(r4.text[:500])
            print()

            # Try restrictions endpoint
            print(f"=== GET /people/{child_id}/restrictions ===")
            r5 = client.get(
                f"{BASE_URL}/people/{child_id}/restrictions",
                headers={"Content-Type": "application/json"},
            )
            print(f"HTTP {r5.status_code}")
            if r5.status_code == 200:
                print(json.dumps(r5.json(), indent=2, ensure_ascii=False)[:3000])
            else:
                print(r5.text[:500])
            print()

            # Check deviceInfo from appsandusage - try screentimesettings per device
            for device in data.get("deviceInfo", [])[:2]:
                device_id = device.get("deviceId", "")
                if not device_id:
                    continue
                print(f"=== GET /devices/{device_id}/screenTimeSettings (or similar) ===")
                for endpoint in [
                    f"{BASE_URL}/devices/{device_id}",
                    f"{BASE_URL}/devices/{device_id}/screentime",
                    f"{BASE_URL}/people/{child_id}/devices/{device_id}",
                ]:
                    r6 = client.get(endpoint, headers={"Content-Type": "application/json"})
                    print(f"  {endpoint}: HTTP {r6.status_code}")
                    if r6.status_code == 200:
                        print(json.dumps(r6.json(), indent=2, ensure_ascii=False)[:1000])
                print()

            # Show ALL top-level keys of appsandusage for analysis
            print("=== appsandusage top-level keys with non-app fields ===")
            for k, v in data.items():
                if k not in ("apps", "appUsageSessions", "deviceInfo"):
                    print(f"  {k}: {json.dumps(v)[:200]}")
            print()
            break


if __name__ == "__main__":
    main()
