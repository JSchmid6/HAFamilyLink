"""Shared pytest fixtures for HAFamilyLink integration tests.

The test suite intentionally avoids a full Home Assistant installation.
Home Assistant modules are stubbed out via ``sys.modules`` in this file so
the integration sources can be imported without the HA package being present.
"""
from __future__ import annotations

import sys
import types
from collections.abc import Generator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal Home Assistant stubs – inserted before any integration import
# ---------------------------------------------------------------------------

def _make_module(name: str, **attrs: Any) -> types.ModuleType:
	"""Create a named stub module with the given attributes."""
	mod = types.ModuleType(name)
	mod.__dict__.update(attrs)
	sys.modules[name] = mod
	return mod


# voluptuous (validation library used by config_flow and llm_api)
vol = _make_module("voluptuous")
# minimal vol.Schema / decorators used in the integration
vol.Schema = lambda s, **kw: s  # type: ignore[attr-defined]
vol.Required = lambda key, **kw: key  # type: ignore[attr-defined]
vol.Optional = lambda key, **kw: key  # type: ignore[attr-defined]
vol.All = lambda *args, **kw: args[0] if args else None  # type: ignore[attr-defined]
vol.Coerce = lambda t: t  # type: ignore[attr-defined]
vol.Range = lambda **kw: None  # type: ignore[attr-defined]
vol.In = lambda v: None  # type: ignore[attr-defined]


# homeassistant.core
_make_module("homeassistant", HomeAssistant=MagicMock())
_make_module("homeassistant.core", HomeAssistant=MagicMock())

# homeassistant.config_entries
ConfigEntry = MagicMock()
OptionsFlow = MagicMock()
ConfigFlow = MagicMock()
_callback = lambda f: f  # noqa: E731
_make_module(
	"homeassistant.config_entries",
	ConfigEntry=ConfigEntry,
	OptionsFlow=OptionsFlow,
	ConfigFlow=ConfigFlow,
	callback=_callback,
)

# homeassistant.const
_make_module("homeassistant.const", Platform=MagicMock(SWITCH="switch", SENSOR="sensor", NUMBER="number"))

# homeassistant.exceptions
_make_module(
	"homeassistant.exceptions",
	ConfigEntryNotReady=Exception,
	HomeAssistantError=Exception,
)

# homeassistant.helpers.*
_make_module("homeassistant.helpers")
class _DataUpdateCoordinator:
	last_update_success = True
	data: Any = None

	def __init__(self, hass: Any, logger: Any, *, name: str, update_interval: Any) -> None:
		self.hass = hass
		self._logger = logger
		self.name = name
		self.update_interval = update_interval

	def async_update_listeners(self) -> None:
		pass

	async def async_request_refresh(self) -> None:
		pass

	async def async_config_entry_first_refresh(self) -> None:
		pass


_make_module(
	"homeassistant.helpers.update_coordinator",
	DataUpdateCoordinator=_DataUpdateCoordinator,
	UpdateFailed=Exception,
)

_llm_mod = _make_module("homeassistant.helpers.llm", API=object, APIInstance=object, Tool=object)
_llm_mod.async_register_api = MagicMock()

_make_module(
	"homeassistant.helpers.entity",
	DeviceInfo=dict,
)
_make_module(
	"homeassistant.helpers.device_registry",
	DeviceEntryType=MagicMock(SERVICE="service"),
)
_make_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock())
_make_module(
	"homeassistant.helpers.update_coordinator",
	DataUpdateCoordinator=_DataUpdateCoordinator,
	UpdateFailed=Exception,
	CoordinatorEntity=object,
)

# homeassistant.components.*
_make_module("homeassistant.components")
_make_module("homeassistant.components.switch", SwitchEntity=object)
_make_module(
	"homeassistant.components.sensor",
	SensorEntity=object,
	SensorDeviceClass=MagicMock(),
	SensorStateClass=MagicMock(),
)
_make_module(
	"homeassistant.components.number",
	NumberEntity=object,
	NumberMode=MagicMock(BOX="box"),
)

# homeassistant.util.*
_make_module("homeassistant.util")
_make_module("homeassistant.util.dt")
_make_module("homeassistant.util.json", JsonObjectType=dict)

# homeassistant.data_entry_flow
_make_module("homeassistant.data_entry_flow", FlowResult=dict)

# homeassistant.const extras
sys.modules["homeassistant.const"].UnitOfTime = MagicMock(MINUTES="min")

# ---------------------------------------------------------------------------
# Test constants & factories
# ---------------------------------------------------------------------------

CHILD_ID_1 = "user_child_001"
CHILD_ID_2 = "user_child_002"

MOCK_CHILDREN = [
	{"child_id": CHILD_ID_1, "name": "Emma", "email": "emma@example.com"},
	{"child_id": CHILD_ID_2, "name": "Luca", "email": "luca@example.com"},
]


def _make_app_usage_session(
	pkg: str,
	seconds: int,
	day: date | None = None,
) -> dict[str, Any]:
	"""Build a minimal appUsageSessions entry."""
	d = day or date.today()
	return {
		"appId": {"androidAppPackageName": pkg},
		"usage": f"{seconds}s",
		"date": {"year": d.year, "month": d.month, "day": d.day},
	}


def make_raw_apps_and_usage(child_id: str = CHILD_ID_1) -> dict[str, Any]:
	"""Return a minimal mock appsandusage API response."""
	return {
		"apps": [
			{
				"packageName": "com.google.android.youtube",
				"title": "YouTube",
				"supervisionSetting": {
					"usageLimit": {"dailyUsageLimitMins": 60},
				},
			},
			{
				"packageName": "com.android.chrome",
				"title": "Chrome",
				"supervisionSetting": {},
			},
			{
				"packageName": "com.tiktok.android",
				"title": "TikTok",
				"supervisionSetting": {"hidden": True},
			},
		],
		"appUsageSessions": [
			_make_app_usage_session("com.google.android.youtube", 3600),
			_make_app_usage_session("com.android.chrome", 1200),
		],
	}


import pytest


@pytest.fixture
def mock_config_entry() -> MagicMock:
	"""Return a minimal mock ConfigEntry."""
	entry = MagicMock()
	entry.entry_id = "test_entry_id"
	entry.data = {
		"name": "Family Link",
		"update_interval": 60,
		"timeout": 30,
		"cookies": [],
	}
	entry.options = {}
	entry.add_update_listener = MagicMock(return_value=lambda: None)
	entry.async_on_unload = MagicMock()
	return entry


@pytest.fixture
def mock_client() -> MagicMock:
	"""Return a mock FamilyLinkClient with sensible defaults."""
	client = AsyncMock()
	client.async_authenticate = AsyncMock()
	client.async_get_members = AsyncMock(return_value=MOCK_CHILDREN)
	client.async_get_apps_and_usage = AsyncMock(
		side_effect=lambda child_id: make_raw_apps_and_usage(child_id)
	)
	client.async_update_app_restriction = AsyncMock()
	client.async_cleanup = AsyncMock()
	return client

