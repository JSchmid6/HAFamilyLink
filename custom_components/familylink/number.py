"""Number platform for Google Family Link – per-app daily time limits.

For each supervised child, a ``NumberEntity`` is created for **every**
supervisable app (all apps that have ``capabilityUsageLimit`` and are neither
blocked nor always-allowed).  A value of ``0`` means no limit; setting ``0``
removes an existing limit.

.. note::
   A device-level overall screen time limit (one shared budget across all
   apps) is **not** exposed by the ``kidsmanagement-pa`` REST API and cannot
   be implemented here without reverse-engineering a different Google endpoint.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FAMILYLINK_BASE_URL, LOGGER_NAME
from .coordinator import FamilyLinkDataUpdateCoordinator

_LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup_entry(
hass: HomeAssistant,
entry: ConfigEntry,
async_add_entities: AddEntitiesCallback,
) -> None:
"""Set up per-app time-limit entities for all supervisable apps."""
coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

entities: list[AppTimeLimitNumber] = []
if coordinator.data:
children: list[dict[str, Any]] = coordinator.data.get("children", [])
restrictions: dict[str, Any] = coordinator.data.get("restrictions", {})
for child in children:
cid = child["child_id"]
child_restrictions = restrictions.get(cid, {})

# Lookup: title -> current limit (None = no limit)
limited_lookup: dict[str, int | None] = {
ai["app"]: ai.get("limit_minutes")
for ai in child_restrictions.get("limited", [])
}

# Create one entity per supervisable app
for sup_app in child_restrictions.get("supervisable", []):
title = sup_app["title"]
current_limit = limited_lookup.get(title, 0) or 0
entities.append(
AppTimeLimitNumber(coordinator, child, title, current_limit)
)

async_add_entities(entities, update_before_add=True)


class AppTimeLimitNumber(CoordinatorEntity, NumberEntity):
"""Adjustable daily time limit (minutes) for one app on a child device.

A value of ``0`` means the app is unrestricted (no per-app limit).  Setting
the entity to ``0`` will remove an existing limit; setting it to ``> 0``
will create or update the limit.
"""

_attr_mode = NumberMode.BOX
_attr_native_min_value = 0.0
_attr_native_max_value = 480.0
_attr_native_step = 15.0
_attr_native_unit_of_measurement = UnitOfTime.MINUTES
_attr_icon = "mdi:timer-edit-outline"

def __init__(
self,
coordinator: FamilyLinkDataUpdateCoordinator,
child: dict[str, Any],
app_name: str,
initial_limit_minutes: int,
) -> None:
"""Initialize the number entity."""
super().__init__(coordinator)
self._child_id: str = child["child_id"]
self._child_name: str = child.get("name", self._child_id)
self._app_name: str = app_name

slug = app_name.lower().replace(" ", "_").replace(".", "_")
self._attr_name = f"{self._child_name} {app_name} Daily Limit"
self._attr_unique_id = f"{DOMAIN}_{self._child_id}_{slug}_limit"

@property
def device_info(self) -> DeviceInfo:
"""Group the entity under the child HA device."""
return DeviceInfo(
identifiers={(DOMAIN, self._child_id)},
name=self._child_name,
manufacturer="Google",
model="Supervised Child",
entry_type=DeviceEntryType.SERVICE,
configuration_url=FAMILYLINK_BASE_URL,
)

@property
def native_value(self) -> float | None:
"""Return the current limit in minutes, or 0 if no limit is set."""
if not self.coordinator.data:
return None
restrictions = (
self.coordinator.data.get("restrictions", {}).get(self._child_id, {})
)
for app_info in restrictions.get("limited", []):
if app_info["app"] == self._app_name:
limit = app_info.get("limit_minutes")
return float(limit) if limit is not None else 0.0
return 0.0  # Not in limited -> no limit currently set

async def async_set_native_value(self, value: float) -> None:
"""Push the updated time limit to Google Family Link.

A value of 0 removes the limit; any other value sets a new limit.
"""
if int(value) == 0:
await self.coordinator.async_remove_app_limit(self._child_id, self._app_name)
else:
await self.coordinator.async_set_app_limit(
self._child_id, self._app_name, int(value)
)
await self.coordinator.async_request_refresh()