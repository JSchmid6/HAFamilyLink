---
name: ha-coordinator-pattern
description: >
  Explains the layered architecture of this integration: coordinator →
  client → API. Use this skill when refactoring, adding new data sources,
  or understanding how data flows from the Google API to HA entities and
  LLM tools.
---

## Layer overview

```
HA Entities / LLM Tools
        │
        ▼
FamilyLinkDataUpdateCoordinator   (coordinator.py)
        │  polls every DEFAULT_UPDATE_INTERVAL seconds
        │  exposes async_* action methods for tools
        ▼
FamilyLinkClient                  (client/api.py)
        │  manages aiohttp session + auth headers
        │  translates HA calls → HTTP requests
        ▼
Google Kids Management API        (unofficial REST)
  kidsmanagement-pa.clients6.google.com/kidsmanagement/v1
```

---

## Coordinator (`coordinator.py`)

Extends `DataUpdateCoordinator[dict[str, Any]]`.

### `_async_update_data`
Called automatically on the poll interval.  Returns `{"devices": [...]}` –
a list of supervised children used by the switch platform.

### `_async_setup_client`
Lazy-initialises `self.client` (a `FamilyLinkClient`).  Called by
`_async_update_data` and every `async_*` action method.

### Action methods (called by LLM tools)
Every public async method is a thin wrapper that:
1. Ensures the client is set up (`if self.client is None: await _async_setup_client()`)
2. Delegates to `self.client.async_*()`
3. Does minimal post-processing (e.g. filtering today's sessions)

Current action methods:
- `async_get_members()`
- `async_get_app_usage(child_id)`
- `async_get_app_restrictions(child_id)`
- `async_set_app_limit(child_id, app_name, minutes)`
- `async_block_app(child_id, app_name)`
- `async_allow_app(child_id, app_name)`
- `async_remove_app_limit(child_id, app_name)`
- `async_control_device(device_id, action)`  ← legacy, used by switch platform

---

## Client (`client/api.py`)

Manages the `aiohttp.ClientSession` and all HTTP communication.

### Important internal methods
- `_get_session()` – lazily creates/returns the session with cookies baked in
- `_auth_headers()` – generates fresh `SAPISIDHASH` headers per-call
- `_get_sapisid()` – extracts SAPISID cookie from `SessionManager`
- `_resolve_package(child_id, app_name)` – maps human title → package name

### App cache
`self._app_cache[child_id]` is a `{title.lower(): package_name}` dict.
It is populated on the first call to `async_get_apps_and_usage(child_id)`.

---

## Adding new data to the coordinator

1. Add the HTTP call to `client/api.py` as `async_get_*` or `async_update_*`.
2. Add a coordinator wrapper method in `coordinator.py`.
3. Optionally cache the result in `_async_update_data` so entities can read
   it without an extra HTTP call.
4. If exposing via an entity, add it to the relevant platform file
   (`sensor.py`, `switch.py`, etc.) and register it in `PLATFORMS` in
   `__init__.py`.
5. If exposing to LLMs, add a `Tool` class in `llm_api.py` and register it
   in `FamilyLinkLLMAPI.async_get_api_instance`.

---

## Error propagation

| Layer | Exception | HA handling |
|---|---|---|
| `client/api.py` | `NetworkError`, `DeviceControlError` | caught by coordinator |
| `client/api.py` | `AuthenticationError`, `SessionExpiredError` | re-raised to coordinator |
| `coordinator.py` | `SessionExpiredError` | calls `_async_refresh_auth()` → reauth flow |
| `coordinator.py` | other `FamilyLinkException` | raises `UpdateFailed` |
| LLM tool | `HomeAssistantError` | returned as error response to the LLM |

---

## Key constants (`const.py`)

| Constant | Value |
|---|---|
| `KIDSMANAGEMENT_BASE_URL` | `https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1` |
| `FAMILYLINK_ORIGIN` | `https://familylink.google.com` |
| `GOOG_API_KEY` | `AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw` |
| `DEFAULT_UPDATE_INTERVAL` | `60` (seconds) |
| `DOMAIN` | `familylink` |
| `LOGGER_NAME` | `custom_components.familylink` |

Always use these constants – never hardcode URLs or the API key.
