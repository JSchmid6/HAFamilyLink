---
name: familylink-api-reference
description: >
  Reference for the unofficial Google Kids Management API used by this
  integration. Use this skill when editing client/api.py, adding new API
  calls, or debugging HTTP errors from the Google API.
---

## Base URL

```
https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1
```

Python constant: `KIDSMANAGEMENT_BASE_URL` in `const.py`.

---

## Authentication

All requests require two things:

### 1. Cookie jar
The full browser cookie jar (from the stored session) must be attached to the
`aiohttp.ClientSession`.  The most important cookies are the Google auth
cookies (`SAPISID`, `SID`, `__Secure-1PSID`, etc.).

### 2. Per-request Authorization header
Generate a fresh `SAPISIDHASH` token for every request:

```
Authorization: SAPISIDHASH {timestamp_ms}_{sha1("{timestamp_ms} {SAPISID} {origin}")}
```

- `origin` = `https://familylink.google.com`  (constant `FAMILYLINK_ORIGIN`)
- The SHA-1 is computed as UTF-8 bytes.
- The timestamp is **milliseconds** since epoch (`int(time.time() * 1000)`).

Helper in `client/api.py`: `_sapisidhash(sapisid, origin) -> str`

### 3. Additional headers
```
Origin:          https://familylink.google.com
X-Goog-Api-Key:  AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw
Content-Type:    application/json              (GET requests)
Content-Type:    application/json+protobuf     (POST requests)
User-Agent:      Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0
```

---

## Endpoints

### GET `/families/mine/members`
Returns all family members.  Supervised children have
`memberSupervisionInfo.isSupervisedMember == true`.

Key fields per member:
- `userId` → use as `child_id` in all other requests
- `profile.displayName`, `profile.email`
- `role` (`"child"` / `"parent"` / `"member"`)

### GET `/people/{child_id}/appsandusage`
Query params: `capabilities=CAPABILITY_APP_USAGE_SESSION&capabilities=CAPABILITY_SUPERVISION_CAPABILITIES`

Returns:
- `apps[]` – installed apps with `packageName`, `title`, `supervisionSetting`
  - `supervisionSetting.hidden` = blocked
  - `supervisionSetting.usageLimit.dailyUsageLimitMins` = daily limit
  - `supervisionSetting.alwaysAllowedAppInfo.alwaysAllowedState` = always allowed
- `appUsageSessions[]` – per-app usage sessions
  - `date.year/month/day`
  - `usage` = duration as `"NNs"` string (seconds with decimal)
  - `appId.androidAppPackageName`
- `deviceInfo[]` – child's registered devices

### POST `/people/{child_id}/apps:updateRestrictions`
Content-Type: `application/json+protobuf`

Body is a JSON-encoded protobuf array:
```
["{child_id}", [[restriction]]]
```

Restriction formats:
| Intent | Payload |
|---|---|
| Block app | `[[pkg], [1]]` |
| Always allow | `[[pkg], null, null, [1]]` |
| Set time limit | `[[pkg], null, [minutes, 1]]` |
| Remove limit | `[[pkg]]` |

Where `pkg` is the Android package name string (e.g. `"com.google.android.youtube"`).

---

## App package name resolution

Call `GET /people/{child_id}/appsandusage` first to build a
`{title.lower() → package_name}` cache (`self._app_cache[child_id]`).
See `_resolve_package` in `client/api.py`.

---

## Common HTTP error codes

| Status | Meaning |
|---|---|
| 400 | Bad request – usually malformed restriction payload |
| 401 | SAPISID cookie missing or expired |
| 403 | Forbidden – wrong `Origin` header or revoked session |
| 404 | `child_id` not found or not supervised |
| 429 | Rate limited – back off and retry |

All HTTP errors are caught and re-raised as `NetworkError` or
`DeviceControlError` from `exceptions.py`.
