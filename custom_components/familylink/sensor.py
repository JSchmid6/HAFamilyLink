"""Sensor platform for Google Family Link – daily screen time.

Creates one sensor per supervised child that shows the total screen time
used today (in minutes).  The ``top_apps`` state attribute contains a list
of the five most-used apps for that child today.

Additionally creates one ``DeviceScreenTimeSensor`` per physical device
linked to each child, sourced from the ``appliedTimeLimits`` API.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
	SensorDeviceClass,
	SensorEntity,
	SensorStateClass,
)
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
	"""Set up screen-time sensors for children and their physical devices."""
	coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

	entities: list[SensorEntity] = []
	if coordinator.data and "children" in coordinator.data:
		children: list[dict[str, Any]] = coordinator.data["children"]
		devices_map: dict[str, list[dict[str, Any]]] = coordinator.data.get("devices", {})

		for child in children:
			# Per-child aggregate sensor (app-usage-based)
			entities.append(ChildScreenTimeSensor(coordinator, child))

			# Per-physical-device sensors
			for dev in devices_map.get(child["child_id"], []):
				entities.append(DeviceScreenTimeSensor(coordinator, child, dev["device_id"]))

	async_add_entities(entities, update_before_add=True)


class ChildScreenTimeSensor(CoordinatorEntity, SensorEntity):
	"""Total daily screen time (minutes) for a supervised child."""

	_attr_device_class = SensorDeviceClass.DURATION
	_attr_state_class = SensorStateClass.MEASUREMENT
	_attr_native_unit_of_measurement = UnitOfTime.MINUTES
	_attr_icon = "mdi:cellphone-clock"
	_attr_suggested_display_precision = 0

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
	) -> None:
		"""Initialize the sensor."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)
		self._attr_name = f"{self._child_name} Screen Time Today"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_screen_time"

	@property
	def device_info(self) -> DeviceInfo:
		"""Return device info so the sensor groups under the child's HA device."""
		return DeviceInfo(
			identifiers={(DOMAIN, self._child_id)},
			name=self._child_name,
			manufacturer="Google",
			model="Supervised Child",
			entry_type=DeviceEntryType.SERVICE,
			configuration_url=FAMILYLINK_BASE_URL,
		)

	@property
	def native_value(self) -> int | None:
		"""Return total screen time today in minutes."""
		if not self.coordinator.data:
			return None
		usage_list: list[dict[str, Any]] = (
			self.coordinator.data.get("usage", {}).get(self._child_id, [])
		)
		total_seconds = sum(item.get("usage_seconds", 0) for item in usage_list)
		return round(total_seconds / 60)

	@property
	def extra_state_attributes(self) -> dict[str, Any]:
		"""Return per-app breakdown (top 5) as extra attributes."""
		usage_list: list[dict[str, Any]] = []
		if self.coordinator.data:
			usage_list = self.coordinator.data.get("usage", {}).get(self._child_id, [])
		return {
			"child_id": self._child_id,
			"top_apps": [
				{
					"app": item["app_name"],
					"minutes": round(item["usage_seconds"] / 60, 1),
				}
				for item in usage_list[:5]
			],
		}


class DeviceScreenTimeSensor(CoordinatorEntity, SensorEntity):
	"""Screen time used today (minutes) for one physical Android device.

	Data comes from ``appliedTimeLimits`` – updated on every coordinator poll.
	The sensor also exposes lock state, active policy and daily quota as
	extra state attributes.
	"""

	_attr_device_class = SensorDeviceClass.DURATION
	_attr_state_class = SensorStateClass.MEASUREMENT
	_attr_native_unit_of_measurement = UnitOfTime.MINUTES
	_attr_icon = "mdi:cellphone-clock"
	_attr_suggested_display_precision = 0

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
		device_id: str,
	) -> None:
		"""Initialize the device screen-time sensor."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)
		self._device_id: str = device_id

		# Short suffix to make the name unique when a child has multiple devices
		suffix = device_id[-6:]
		self._attr_name = f"{self._child_name} Device ({suffix}) Screen Time"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_{device_id}_screen_time"

	@property
	def device_info(self) -> DeviceInfo:
		"""Group entity under its own HA device, linked to the child device."""
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

	def _device_entry(self) -> dict[str, Any] | None:
		"""Return the coordinator data entry for this device, or None."""
		if not self.coordinator.data:
			return None
		device_list: list[dict[str, Any]] = (
			self.coordinator.data.get("devices", {}).get(self._child_id, [])
		)
		for dev in device_list:
			if dev["device_id"] == self._device_id:
				return dev
		return None

	@property
	def native_value(self) -> int | None:
		"""Return screen time used today in minutes."""
		entry = self._device_entry()
		return entry["usage_minutes_today"] if entry else None

	@property
	def extra_state_attributes(self) -> dict[str, Any]:
		"""Return device lock state, policy and daily quota."""
		entry = self._device_entry()
		if not entry:
			return {"device_id": self._device_id}
		return {
			"device_id": self._device_id,
			"is_locked": entry.get("is_locked"),
			"active_policy": entry.get("active_policy"),
			"override_action": entry.get("override_action"),
			"today_limit_minutes": entry.get("today_limit_minutes"),
		}
