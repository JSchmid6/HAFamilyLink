---
name: add-llm-tool
description: >
  Step-by-step guide for adding a new LLM agent tool (skill) to the
  HAFamilyLink Home Assistant integration. Use this skill whenever the user
  asks to add, rename, or modify a tool that a conversation agent can call.
---

## Overview

LLM tools live exclusively in `custom_components/familylink/llm_api.py`.
Each tool is a class that inherits from `_FamilyLinkTool`, which itself
inherits from `homeassistant.helpers.llm.Tool`.

The tool is wired to the coordinator via `self._coordinator(hass)`, which
returns the `FamilyLinkDataUpdateCoordinator` for the active config entry.
All actual I/O must go through the coordinator (never call `self.client`
directly from a tool).

---

## Step-by-step: adding a new tool

### 1. Add the coordinator method

Open `custom_components/familylink/coordinator.py` and add an `async_*`
method that calls the appropriate client method.

```python
async def async_my_new_action(self, child_id: str, some_param: str) -> dict:
    """Short docstring."""
    if self.client is None:
        await self._async_setup_client()
    return await self.client.async_my_new_action(child_id, some_param)
```

### 2. Add the client method (if the API endpoint is new)

Open `custom_components/familylink/client/api.py` and add an async method
that calls the kidsmanagement REST API.  Always use `self._get_session()` and
`self._auth_headers()`.  Raise `NetworkError` on HTTP errors and
`DeviceControlError` on control failures.

Base URL constant: `KIDSMANAGEMENT_BASE_URL`
(`https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1`)

### 3. Write the tool class in `llm_api.py`

```python
class MyNewTool(_FamilyLinkTool):
    """One-line description shown to the LLM."""

    name = "MyNewTool"             # CamelCase, unique
    description = (
        "Detailed description. Explain WHEN and HOW the LLM should call it. "
        "Mention which other tools must be called first (e.g., GetChildren)."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
            vol.Required("some_param", description="..."): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args = tool_input.tool_args
        result = await self._coordinator(hass).async_my_new_action(
            args["child_id"], args["some_param"]
        )
        return {"success": True, **result}
```

### 4. Register the tool in `FamilyLinkLLMAPI.async_get_api_instance`

Add `MyNewTool(self._entry_id)` to the `tools=[ ... ]` list inside
`async_get_api_instance`.

### 5. Bump the version

Every code change requires a `MINOR` or `PATCH` bump in
`custom_components/familylink/manifest.json` – see the `version-management`
skill for rules.

---

## Rules & conventions

- `name` must be **unique** across all tools.  Use CamelCase.
- `description` is the most important attribute – a bad description means the
  LLM will call the wrong tool or miss it entirely.
- `parameters` uses `voluptuous`.  Mark rarely-needed params `vol.Optional`.
- Return a plain `dict` (`JsonObjectType`).  Never raise in the return value –
  raise `HomeAssistantError` for errors.
- `child_id` is always obtained from `GetChildren` first. Remind the LLM of
  this in the `description`.
- Tools must be stateless – all state lives in the coordinator.
