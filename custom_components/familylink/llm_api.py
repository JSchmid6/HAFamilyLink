"""LLM API for Google Family Link.

Registers agent skills (tools) that allow a Home Assistant conversation agent
(e.g. Google Extended, OpenAI, local LLMs via Ollama) to control Family Link
parental controls via natural language.

Available tools
---------------
* GetChildren         – list supervised children in the family
* GetScreenTime       – today's per-app usage for a child
* GetAppRestrictions  – current limits / blocks / always-allowed apps
* SetAppLimit         – set a daily time limit for an app
* BlockApp            – block an app completely
* AllowApp            – mark an app as always allowed (no restrictions)
* RemoveAppLimit      – remove a time limit from an app
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN, LOGGER_NAME

_LOGGER = logging.getLogger(LOGGER_NAME)


# ---------------------------------------------------------------------------
# Base class – gives every tool access to the coordinator
# ---------------------------------------------------------------------------

class _FamilyLinkTool(llm.Tool):
    """Base class for Family Link tools carrying the config entry ID."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    def _coordinator(self, hass: HomeAssistant):
        """Return the active coordinator for this config entry."""
        try:
            return hass.data[DOMAIN][self._entry_id]
        except KeyError as err:
            raise HomeAssistantError(
                "Family Link integration is not available – please check the integration setup."
            ) from err


# ---------------------------------------------------------------------------
# Individual tools
# ---------------------------------------------------------------------------

class GetChildrenTool(_FamilyLinkTool):
    """Returns a list of supervised children in the Google family."""

    name = "GetChildren"
    description = (
        "Returns the supervised children in the Google family. "
        "Each child has a 'child_id' (user ID), 'name', and 'email'. "
        "Always call this tool first to obtain child_id values needed by other tools."
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        members = await self._coordinator(hass).async_get_members()
        return {"children": members}


class GetScreenTimeTool(_FamilyLinkTool):
    """Returns today's per-app screen time for a supervised child."""

    name = "GetScreenTime"
    description = (
        "Returns today's app usage (screen time) for a supervised child. "
        "Results include app name and duration in seconds. "
        "Use GetChildren first to obtain the child_id."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        child_id: str = tool_input.tool_args["child_id"]
        usage = await self._coordinator(hass).async_get_app_usage(child_id)
        return {"child_id": child_id, "screen_time_today": usage}


class GetAppRestrictionsTool(_FamilyLinkTool):
    """Returns current app restrictions for a supervised child."""

    name = "GetAppRestrictions"
    description = (
        "Returns the current app restrictions for a supervised child: "
        "apps with a daily time limit, blocked apps, and always-allowed apps. "
        "Use GetChildren first to obtain the child_id."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        child_id: str = tool_input.tool_args["child_id"]
        restrictions = await self._coordinator(hass).async_get_app_restrictions(child_id)
        return {"child_id": child_id, "restrictions": restrictions}


class SetAppLimitTool(_FamilyLinkTool):
    """Sets a daily time limit for an app on a child's device."""

    name = "SetAppLimit"
    description = (
        "Sets a daily time limit in minutes for a specific app on a child's device. "
        "Example: limit YouTube to 30 minutes per day. "
        "The app_name must match exactly (e.g. 'YouTube', 'Spotify', 'Fortnite'). "
        "Alternatively you can pass the Android package name directly."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
            vol.Required("app_name", description="App title or Android package name"): str,
            vol.Required(
                "minutes",
                description="Daily time limit in minutes (1–1440)",
            ): vol.All(int, vol.Range(min=1, max=1440)),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args: dict[str, Any] = tool_input.tool_args
        await self._coordinator(hass).async_set_app_limit(
            args["child_id"], args["app_name"], args["minutes"]
        )
        return {
            "success": True,
            "child_id": args["child_id"],
            "app": args["app_name"],
            "limit_minutes": args["minutes"],
        }


class BlockAppTool(_FamilyLinkTool):
    """Blocks an app on a child's device completely."""

    name = "BlockApp"
    description = (
        "Blocks a specific app on a child's device so the child cannot open it at all. "
        "Use AllowApp or SetAppLimit to reverse this."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
            vol.Required("app_name", description="App title or Android package name"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args: dict[str, Any] = tool_input.tool_args
        await self._coordinator(hass).async_block_app(args["child_id"], args["app_name"])
        return {"success": True, "child_id": args["child_id"], "app": args["app_name"], "status": "blocked"}


class AllowAppTool(_FamilyLinkTool):
    """Marks an app as always allowed (removes any time limit or block)."""

    name = "AllowApp"
    description = (
        "Marks an app as 'always allowed' on a child's device. "
        "This removes any previous time limit or block for that app."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
            vol.Required("app_name", description="App title or Android package name"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args: dict[str, Any] = tool_input.tool_args
        await self._coordinator(hass).async_allow_app(args["child_id"], args["app_name"])
        return {
            "success": True,
            "child_id": args["child_id"],
            "app": args["app_name"],
            "status": "always_allowed",
        }


class RemoveAppLimitTool(_FamilyLinkTool):
    """Removes the daily time limit for an app (without blocking or always-allowing it)."""

    name = "RemoveAppLimit"
    description = (
        "Removes the daily time limit for a specific app on a child's device. "
        "The app will not be explicitly blocked or allowed – it reverts to the default "
        "supervised state for that child."
    )
    parameters = vol.Schema(
        {
            vol.Required("child_id", description="The user ID of the child"): str,
            vol.Required("app_name", description="App title or Android package name"): str,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        args: dict[str, Any] = tool_input.tool_args
        await self._coordinator(hass).async_remove_app_limit(args["child_id"], args["app_name"])
        return {
            "success": True,
            "child_id": args["child_id"],
            "app": args["app_name"],
            "limit_removed": True,
        }


# ---------------------------------------------------------------------------
# LLM API class
# ---------------------------------------------------------------------------

class FamilyLinkLLMAPI(llm.API):
    """Registers Family Link tools with Home Assistant's LLM API framework."""

    def __init__(self, hass: HomeAssistant, entry_id: str, entry_title: str) -> None:
        super().__init__(
            hass=hass,
            id=f"{DOMAIN}-{entry_id}",
            name=f"Family Link – {entry_title}",
        )
        self._entry_id = entry_id

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Create an API instance with all Family Link tools."""
        return llm.APIInstance(
            api=self,
            api_prompt=(
                "You can manage Google Family Link parental controls for supervised children. "
                "Always call GetChildren first to discover available children and their IDs. "
                "App names must match exactly as they appear in the Google Play Store "
                "(e.g. 'YouTube', 'Spotify', 'Fortnite', 'Minecraft'). "
                "You may also use the Android package name directly (e.g. 'com.google.android.youtube'). "
                "Call GetScreenTime to check current usage before setting or adjusting limits."
            ),
            llm_context=llm_context,
            tools=[
                GetChildrenTool(self._entry_id),
                GetScreenTimeTool(self._entry_id),
                GetAppRestrictionsTool(self._entry_id),
                SetAppLimitTool(self._entry_id),
                BlockAppTool(self._entry_id),
                AllowAppTool(self._entry_id),
                RemoveAppLimitTool(self._entry_id),
            ],
        )


# ---------------------------------------------------------------------------
# Registration helper called from __init__.py
# ---------------------------------------------------------------------------

def async_register_llm_api(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the Family Link LLM API and schedule deregistration on unload."""
    unreg = llm.async_register_api(
        hass,
        FamilyLinkLLMAPI(hass, entry.entry_id, entry.title),
    )
    entry.async_on_unload(unreg)
    _LOGGER.debug("Registered Family Link LLM API for entry '%s'", entry.title)
