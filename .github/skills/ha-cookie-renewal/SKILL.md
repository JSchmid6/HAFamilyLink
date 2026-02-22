````skill
---
name: ha-cookie-renewal
description: >
  Reusable pattern for automatic cookie renewal in Home Assistant integrations
  that use manual cookie-header injection with aiohttp. Covers Set-Cookie
  capture via TraceConfig, persisting renewed cookies back to the config entry,
  and the reload-guard pattern that prevents async_update_entry from triggering
  a full entry reload. Transfer this skill to any HA integration with
  cookie-based authentication.
---

## Problem

When cookies are injected as a flat `Cookie:` header (instead of using the
aiohttp CookieJar), `Set-Cookie` response headers from the server are silently
discarded.  This means cookies that Google (or another provider) automatically
refreshes on every response are never persisted – the stored cookies go stale.

---

## Solution overview

1. Install an aiohttp `TraceConfig` hook (`on_request_end`) that reads
   `Set-Cookie` headers from every response.
2. Buffer the renewed `name → value` pairs in-memory.
3. After each coordinator update cycle, merge the buffer into the stored
   cookie list and persist via `hass.config_entries.async_update_entry()`.
4. Guard `add_update_listener` so that this data-only write does **not**
   trigger a full entry reload.

---

## Step 1 – Capture Set-Cookie in the aiohttp session

Use `on_request_end`, **not** `on_response_headers_received`.
`on_response_headers_received` was added in aiohttp 3.10 and is not available
in the aiohttp version shipped with Home Assistant.

```python
import http.cookies
import aiohttp

class MyApiClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._pending_cookie_updates: dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            trace_config = aiohttp.TraceConfig()

            async def _on_request_end(
                _session: aiohttp.ClientSession,
                _ctx: object,
                params: aiohttp.TraceRequestEndParams,
            ) -> None:
                self._capture_set_cookies(params.response.headers)

            trace_config.on_request_end.append(_on_request_end)

            self._session = aiohttp.ClientSession(
                trace_configs=[trace_config],
            )
        return self._session

    def _capture_set_cookies(self, headers: object) -> None:
        for cookie_str in headers.getall("Set-Cookie", []):
            sc: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
            try:
                sc.load(cookie_str)
            except http.cookies.CookieError:
                continue
            for name, morsel in sc.items():
                self._pending_cookie_updates[name] = morsel.value

    def get_updated_cookies(self) -> list[dict]:
        """Merge pending renewals into the stored list and clear the buffer."""
        original = list(self.session_manager.get_cookies())  # your storage
        if not self._pending_cookie_updates:
            return original
        updates = dict(self._pending_cookie_updates)
        merged = [
            {**c, "value": updates[c["name"]]} if c.get("name") in updates else c
            for c in original
        ]
        # Also update in-memory session so next request uses fresh values
        if self.session_manager._session_data is not None:
            self.session_manager._session_data["cookies"] = merged
        self._pending_cookie_updates.clear()
        return merged
```

---

## Step 2 – Persist from the coordinator

Add `_async_persist_cookies()` and call it at the end of every successful
`_async_update_data()` run:

```python
async def _async_update_data(self) -> dict:
    ...
    result = {...}
    await self._async_persist_cookies()   # ← always last, before return
    return result

async def _async_persist_cookies(self) -> None:
    if self.client is None:
        return
    try:
        updated = self.client.get_updated_cookies()
    except Exception as err:
        _LOGGER.debug("Cookie persistence skipped: %s", err)
        return
    if not updated:
        return
    new_data = {**self.entry.data, "cookies": updated}
    self.hass.config_entries.async_update_entry(self.entry, data=new_data)
    _LOGGER.debug("Persisted %d cookie(s) after auto-renewal", len(updated))
```

---

## Step 3 – Reload guard in `__init__.py`

`hass.config_entries.async_update_entry()` fires **all** `add_update_listener`
callbacks, including the one that reloads the entry on options changes.
A data-only write (cookie renewal) must NOT trigger a reload.

**Pattern:** snapshot `entry.options` at setup time; only reload when options
actually differ.

```python
async def async_setup_entry(hass, entry):
    ...
    _options_snapshot = dict(entry.options)

    async def _async_options_updated(hass, entry):
        if dict(entry.options) != _options_snapshot:
            await async_reload_entry(hass, entry)
        # else: data-only write (e.g. cookie renewal) – skip reload

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
```

Without this guard you get:
```
ConfigEntryError: async_config_entry_first_refresh called when config entry
state is ConfigEntryState.LOADED, but should only be called in state
ConfigEntryState.SETUP_IN_PROGRESS
```
and duplicate entity ID errors on every cookie renewal cycle.

---

## aiohttp version compatibility notes

| Signal | Available since | Notes |
|---|---|---|
| `on_request_end` | aiohttp 3.0 | ✅ Safe to use in HA |
| `on_response_chunk_received` | aiohttp 3.0 | ✅ Safe, but only gives body chunks |
| `on_response_headers_received` | aiohttp 3.10 | ❌ NOT available in HA's bundled aiohttp |

Always use `on_request_end` for response header inspection in HA integrations.
````
