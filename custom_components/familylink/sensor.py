"""Sensor platform for Google Family Link – daily screen time.

Creates one sensor per supervised child that shows the total screen time
used today (in minutes).  The ``top_apps`` state attribute contains a list
of the five most-used apps for that child today.
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
	"""Set up one screen-time sensor per supervised child."""
	coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

	entities: list[ChildScreenTimeSensor] = []
	if coordinator.data and "children" in coordinator.data:
		for child in coordinator.data["children"]:
			entities.append(ChildScreenTimeSensor(coordinator, child))

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
