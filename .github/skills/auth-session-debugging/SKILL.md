---
name: auth-session-debugging
description: >
  Guide for debugging authentication and session problems in the HAFamilyLink
  integration. Use this skill when the integration logs AuthenticationError,
  SessionExpiredError, HTTP 401/403 errors, or "SAPISID cookie not found".
---

## How authentication works

1. **Login** (one-time, manual): Playwright opens a Chromium browser.  The
   user logs in to `https://families.google.com`.  Cookies are extracted and
   stored encrypted in the HA config entry (`entry.data["cookies"]`).

2. **Every request**: The stored cookie jar is loaded by `SessionManager`.
   The `SAPISID` cookie value is extracted and used to compute a fresh
   `SAPISIDHASH` Authorization header (SHA-1 based, timestamp in ms).

3. **Session validity check** (`SessionManager.is_authenticated`):
   Iterates through `_AUTH_COOKIE_NAMES` and checks the `expires` /
   `expirationDate` field.  A session is invalid only if a critical auth
   cookie has an explicit past expiry timestamp.

---

## Debugging checklist

### "No session data found – authentication required"
- `entry.data["cookies"]` is empty or missing.
- Fix: re-run the config flow (Setup → Re-configure) to trigger a new
  browser login.

### "Session cookies have expired"
- An auth cookie's `expires` timestamp is in the past.
- Fix: re-run the config flow.
- Note: `is_authenticated()` checks these cookie names:
  `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`,
  `__Secure-1PSID`, `__Secure-3PSID`, `__Secure-1PAPISID`, `__Secure-3PAPISID`

### "SAPISID cookie not found"
- The SAPISID cookie is missing from the stored cookie list.
- `_get_sapisid()` in `client/api.py` first looks for `SAPISID` on
  `.google.com`, then falls back to `__Secure-3PAPISID` or `APISID`.
- This can happen if the user logged in with a browser that exports cookies
  in a non-standard format.
- Workaround: export cookies from Firefox / Chrome using an extension that
  outputs standard Netscape/JSON format including the `SAPISID` cookie.

### HTTP 401 from the API
- The SAPISIDHASH is invalid.  Most likely the clock is out of sync
  (timestamp used for the hash is too far from server time).
- Check that the HA host has correct system time (`date` command).

### HTTP 403 from the API
- The `Origin` header is wrong.  Must be exactly `https://familylink.google.com`.
- Or the session was revoked by Google (security event, password change, etc.).
- Fix: re-authenticate.

### Coordinator logs "Session expired – initiating re-authentication"
- `SessionExpiredError` was thrown during `_async_update_data`.
- `coordinator._async_refresh_auth()` is called, which clears the client and
  calls `entry.async_start_reauth(hass)` → triggers the HA reauth flow.

---

## Key files

| File | Role |
|---|---|
| `auth/session.py` | Loads/saves/validates cookies from config entry |
| `auth/browser.py` | Playwright browser login & cookie extraction |
| `client/api.py` | `_get_sapisid()`, `_auth_headers()`, `_get_session()` |
| `coordinator.py` | `_async_refresh_auth()` – triggers reauth flow |
| `config_flow.py` | Login step & reauth step |

---

## Testing auth without HA running

```python
import json, hashlib, time, aiohttp, asyncio

cookies = json.load(open("exported_cookies.json"))
sapisid = next(c["value"] for c in cookies if c["name"] == "SAPISID")
ts = int(time.time() * 1000)
origin = "https://familylink.google.com"
digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
auth = f"SAPISIDHASH {ts}_{digest}"

async def test():
    jar = {c["name"]: c["value"] for c in cookies}
    async with aiohttp.ClientSession(cookies=jar) as s:
        r = await s.get(
            "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1/families/mine/members",
            headers={"Authorization": auth, "Origin": origin,
                     "X-Goog-Api-Key": "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"},
        )
        print(r.status, await r.text())

asyncio.run(test())
```
