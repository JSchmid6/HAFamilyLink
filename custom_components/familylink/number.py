"""Number platform for Google Family Link – per-app daily time limits, device bonus time,
and persistent daily screen time limits (Tageslimit).

For each supervised child, a NumberEntity is created for every supervisable app.
A value of 0 means no limit; setting 0 removes an existing limit.

Additionally, one DeviceBonusTimeNumber is created per physical device.
Setting a value > 0 grants bonus screen time via timeLimitOverrides:batchCreate.
Setting to 0 clears all active overrides.

One DeviceDailyLimitNumber is created per child × day (7 per child),
representing the persistent daily screen time quota (timeLimit endpoint).
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

_DAY_NAMES: dict[int, str] = {
	1: "Monday",
	2: "Tuesday",
	3: "Wednesday",
	4: "Thursday",
	5: "Friday",
	6: "Saturday",
	7: "Sunday",
}


async def async_setup_entry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up per-app time-limit entities and per-device bonus-time entities."""
	coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

	entities: list[NumberEntity] = []
	if coordinator.data:
		children: list[dict[str, Any]] = coordinator.data.get("children", [])
		restrictions: dict[str, Any] = coordinator.data.get("restrictions", {})
		devices_map: dict[str, list[dict[str, Any]]] = coordinator.data.get("devices", {})

		for child in children:
			cid = child["child_id"]
			child_restrictions = restrictions.get(cid, {})
			limited_lookup: dict[str, int | None] = {
				ai["app"]: ai.get("limit_minutes")
				for ai in child_restrictions.get("limited", [])
			}
			for sup_app in child_restrictions.get("supervisable", []):
				title = sup_app["title"]
				current_limit = limited_lookup.get(title, 0) or 0
				entities.append(AppTimeLimitNumber(coordinator, child, title, current_limit))
			for dev in devices_map.get(cid, []):
				entities.append(DeviceBonusTimeNumber(coordinator, child, dev["device_id"]))

			# Daily limit entities (one per day per child)
			daily_limits_map: dict[str, Any] = coordinator.data.get("daily_limits", {})
			for day_num in range(1, 8):
				if day_num in daily_limits_map.get(cid, {}):
					entities.append(DeviceDailyLimitNumber(coordinator, child, day_num))

	async_add_entities(entities)


class AppTimeLimitNumber(CoordinatorEntity, NumberEntity):
	"""Adjustable daily time limit (minutes) for one app on a child device.

	A value of 0 means the app is unrestricted. Setting 0 removes an existing limit.
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
		restrictions = self.coordinator.data.get("restrictions", {}).get(self._child_id, {})
		for app_info in restrictions.get("limited", []):
			if app_info["app"] == self._app_name:
				limit = app_info.get("limit_minutes")
				return float(limit) if limit is not None else 0.0
		return 0.0

	async def async_set_native_value(self, value: float) -> None:
		"""Push the updated time limit to Google Family Link."""
		if int(value) == 0:
			await self.coordinator.async_remove_app_limit(self._child_id, self._app_name)
		else:
			await self.coordinator.async_set_app_limit(
				self._child_id, self._app_name, int(value)
			)
		await self.coordinator.async_request_refresh()


class DeviceBonusTimeNumber(CoordinatorEntity, NumberEntity):
	"""One-shot control to grant bonus screen time for a physical device today.

	Setting N > 0 grants N additional minutes via timeLimitOverrides:batchCreate.
	Setting 0 clears all active overrides (e.g. removes a device lock).
	Always reads back as 0 – bonus time is a command, not persistent state.
	"""

	_attr_mode = NumberMode.BOX
	_attr_native_min_value = 0.0
	_attr_native_max_value = 120.0
	_attr_native_step = 15.0
	_attr_native_unit_of_measurement = UnitOfTime.MINUTES
	_attr_icon = "mdi:timer-plus-outline"

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
		device_id: str,
	) -> None:
		"""Initialize the bonus time number entity."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)
		self._device_id: str = device_id
		suffix = device_id[-6:]
		self._attr_name = f"{self._child_name} Device ({suffix}) Bonus Time"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_{device_id}_bonus_time"

	@property
	def device_info(self) -> DeviceInfo:
		"""Group entity under the physical device HA entry."""
		suffix = self._device_id[-6:]
		return DeviceInfo(
			identifiers={(DOMAIN, self._device_id)},
			name=f"{self._child_name} ({suffix})",
			manufacturer="Google",
			model="Android Device",
			entry_type=DeviceEntryType.SERVICE,
			via_device=(DOMAIN, self._child_id),
			configuration_url=FAMILYLINK_BASE_URL,
		)

	@property
	def native_value(self) -> float:
		"""Always return 0 – bonus time is a write-only command."""
		return 0.0

	async def async_set_native_value(self, value: float) -> None:
		"""Grant bonus time or clear overrides. 0 = clear; N > 0 = grant N minutes."""
		await self.coordinator.async_set_device_bonus_time(
			self._child_id, self._device_id, int(value)
		)
		await self.coordinator.async_request_refresh()


class DeviceDailyLimitNumber(CoordinatorEntity, NumberEntity):
	"""Persistent daily screen time quota for one day of the week.

	Reads from and writes to the ``timeLimit`` endpoint
	(PUT /people/{child_id}/timeLimit:update).  One entity per child per day.
	"""

	_attr_mode = NumberMode.BOX
	_attr_native_min_value = 0.0
	_attr_native_max_value = 720.0
	_attr_native_step = 5.0
	_attr_native_unit_of_measurement = UnitOfTime.MINUTES
	_attr_icon = "mdi:timer-lock-outline"

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
		day_num: int,
	) -> None:
		"""Initialize the daily limit number entity."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)
		self._day_num: int = day_num
		day_name = _DAY_NAMES[day_num]
		self._attr_name = f"{self._child_name} Daily Limit {day_name}"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_daily_limit_{day_num}"

	@property
	def device_info(self) -> DeviceInfo:
		"""Group entity under the child HA device."""
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
		"""Return the current daily limit in minutes."""
		if not self.coordinator.data:
			return None
		day_data = (
			self.coordinator.data.get("daily_limits", {})
			.get(self._child_id, {})
			.get(self._day_num)
		)
		if day_data is None:
			return None
		return float(day_data["quota_mins"])

	async def async_set_native_value(self, value: float) -> None:
		"""Push the updated daily limit to Google Family Link."""
		await self.coordinator.async_set_daily_limit(
			self._child_id, self._day_num, int(value)
		)
		await self.coordinator.async_request_refresh()
