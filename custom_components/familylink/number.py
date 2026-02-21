"""Number platform for Google Family Link – per-app daily time limits.

Two entity types are provided:

1. ``BulkTimeLimitNumber`` (one per child) – sets the same daily limit on
   **all** supervisable apps in a single API call.  This is the closest
   approximation to an "overall daily screen-time" budget: every non-blocked,
   non-always-allowed app receives the same per-app cap.  Setting the value to
   ``0`` removes all per-app limits.

2. ``AppTimeLimitNumber`` (one per supervisable app per child) – adjusts the
   limit on a single app.  Unlike earlier versions, entities are now created
   for **every** supervisable app (not just those that already have a limit
   set).  A value of ``0`` means "no limit / remove existing limit".
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
	"""Set up time-limit entities for all supervisable apps and bulk controls."""
	coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

	entities: list[NumberEntity] = []
	if coordinator.data:
		children: list[dict[str, Any]] = coordinator.data.get("children", [])
		restrictions: dict[str, Any] = coordinator.data.get("restrictions", {})
		for child in children:
			cid = child["child_id"]
			child_restrictions = restrictions.get(cid, {})

			# Build lookup: title → current limit (None = no limit)
			limited_lookup: dict[str, int | None] = {
				ai["app"]: ai.get("limit_minutes")
				for ai in child_restrictions.get("limited", [])
			}

			# 1. Bulk entity – one per child
			entities.append(BulkTimeLimitNumber(coordinator, child))

			# 2. Per-app entities – one for every supervisable app
			for sup_app in child_restrictions.get("supervisable", []):
				title = sup_app["title"]
				current_limit = limited_lookup.get(title, 0) or 0
				entities.append(
					AppTimeLimitNumber(coordinator, child, title, current_limit)
				)

	async_add_entities(entities, update_before_add=True)


# ---------------------------------------------------------------------------
# Bulk "overall" daily limit
# ---------------------------------------------------------------------------

class BulkTimeLimitNumber(CoordinatorEntity, NumberEntity):
	"""Single number entity that applies the same limit to ALL supervised apps.

	Setting this to e.g. 60 sends a single API request that limits every
	non-blocked, non-always-allowed app to 60 minutes per day.  Setting it to
	0 removes all per-app limits.

	The displayed value is:
	  - ``0``  – no apps have any per-app limit (fully open).
	  - ``N``  – every currently limited app shares the same limit of N minutes.
	  - ``None`` (unknown) – apps have inconsistent / different limits.
	"""

	_attr_mode = NumberMode.BOX
	_attr_native_min_value = 0.0
	_attr_native_max_value = 480.0
	_attr_native_step = 15.0
	_attr_native_unit_of_measurement = UnitOfTime.MINUTES
	_attr_icon = "mdi:timer-lock-outline"

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
	) -> None:
		"""Initialize the bulk limit entity."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)

		self._attr_name = f"{self._child_name} Daily Screen Time"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_bulk_daily_limit"

	@property
	def device_info(self) -> DeviceInfo:
		"""Group under the child's HA device."""
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
		"""Return the common limit if all limited apps agree, 0 if none are limited."""
		if not self.coordinator.data:
			return None
		child_restrictions = (
			self.coordinator.data.get("restrictions", {}).get(self._child_id, {})
		)
		supervisable_titles = {
			s["title"] for s in child_restrictions.get("supervisable", [])
		}
		limited_values = {
			ai.get("limit_minutes")
			for ai in child_restrictions.get("limited", [])
			if ai["app"] in supervisable_titles and ai.get("limit_minutes") is not None
		}
		if not limited_values:
			return 0.0  # No per-app limits set
		if len(limited_values) == 1:
			return float(limited_values.pop())  # All share the same limit
		return None  # Mixed limits → unknown

	async def async_set_native_value(self, value: float) -> None:
		"""Apply the limit to every supervisable app in one API call."""
		await self.coordinator.async_set_bulk_limit(self._child_id, int(value))
		await self.coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Per-app limit
# ---------------------------------------------------------------------------

class AppTimeLimitNumber(CoordinatorEntity, NumberEntity):
	"""Adjustable daily time limit (minutes) for one app on a child's device.

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
		"""Group the entity under the child's HA device."""
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
		return 0.0  # Not in limited → no limit currently set

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
