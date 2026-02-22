"""Minimal PUT variants for timeLimit:update."""
import asyncio, hashlib, json, time
import aiohttp
from pathlib import Path

CHILD_ID = "112452138243419815198"
API_BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
API_KEY = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"
ORIGIN = "https://familylink.google.com"
EXT223 = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
EXT202 = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

cookies = {c["name"]: c["value"] for c in json.loads(
    Path(r"C:\Users\Joche\Downloads\familylink.google.com.cookies.json").read_text())}
sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID", "")

def auth():
    ts = int(time.time() * 1000)
    d = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{d}", str(ts)

def hdrs(ct="application/json+protobuf"):
    a, _ = auth()
    return {"Authorization": a, "X-Goog-AuthUser": "0", "X-Goog-Api-Key": API_KEY,
            "Origin": ORIGIN, "Content-Type": ct,
            "x-goog-ext-223261916-bin": EXT223, "x-goog-ext-202964622-bin": EXT202,
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}

async def run():
    url = f"{API_BASE}/people/{CHILD_ID}/timeLimit:update"
    _, now = auth()

    # Monday entry IDs and known data
    MON_ID = "CAEQAQ"
    MON_CRT = "1691759143732"

    variants = {
        # Structure: outer[1]=CHILD_ID, outer[2]=TimeLimitUpdate
        "U1_child_minimal":  [None, CHILD_ID, [None, [[2, [[MON_ID, 1, 2, 41]]]]]],
        "U2_child_ts":       [None, CHILD_ID, [None, [[2, [[MON_ID, 1, 2, 41, MON_CRT, now]]]]]],
        "U3_hdr_child":      [[None, now], CHILD_ID, [None, [[2, [[MON_ID, 1, 2, 41]]]]]],
        "U4_hdr_child_ts":   [[None, now], CHILD_ID, [None, [[2, [[MON_ID, 1, 2, 41, MON_CRT, now]]]]]],
        # Without CHILD_ID in body (already in URL path)
        "U5_no_child":       [None, None, [None, [[2, [[MON_ID, 1, 2, 41]]]]]],
        "U6_no_child_ts":    [None, None, [None, [[2, [[MON_ID, 1, 2, 41, MON_CRT, now]]]]]],
        # state=1 instead of 2
        "U7_state1":         [None, CHILD_ID, [None, [[1, [[MON_ID, 1, 2, 41]]]]]],
        # flat: outer[1] = TimeLimitUpdate directly (no CHILD_ID in body)
        "U8_flat":           [None, [None, [[2, [[MON_ID, 1, 2, 41]]]]]],
        # text/plain content-type
        "U9_plain_ct":       [None, CHILD_ID, [None, [[2, [[MON_ID, 1, 2, 41]]]]]],
    }

    async with aiohttp.ClientSession() as s:
        for label, body_obj in variants.items():
            ct = "text/plain;charset=UTF-8" if label == "U9_plain_ct" else "application/json+protobuf"
            body = json.dumps(body_obj, separators=(",", ":"))
            async with s.post(url, headers=hdrs(ct),
                              params={"$httpMethod": "PUT"}, data=body) as r:
                resp = await r.text()
                print(f"[{label}] {len(body)}B HTTP {r.status}: {resp[:250]}")

asyncio.run(run())
