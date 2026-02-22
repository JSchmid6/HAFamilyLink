"""Switch platform for Google Family Link integration.

One switch per supervised child.  The switch represents whether supervision
is active (always ``True``).  It cannot be physically turned off via HA –
doing so logs a warning and leaves the state unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
	DOMAIN,
	FAMILYLINK_BASE_URL,
	LOGGER_NAME,
)
from .coordinator import FamilyLinkDataUpdateCoordinator

_LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup_entry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up one switch entity per supervised child."""
	coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

	entities: list[ChildSupervisionSwitch] = []
	if coordinator.data and "children" in coordinator.data:
		for child in coordinator.data["children"]:
			entities.append(ChildSupervisionSwitch(coordinator, child))

	async_add_entities(entities, update_before_add=True)


class ChildSupervisionSwitch(CoordinatorEntity, SwitchEntity):
	"""Switch indicating that supervision is active for a child.

	The switch is always ``on`` (supervision cannot be disabled through HA).
	"""

	_attr_icon = "mdi:account-child-circle"
	_attr_has_entity_name = True

	def __init__(
		self,
		coordinator: FamilyLinkDataUpdateCoordinator,
		child: dict[str, Any],
	) -> None:
		"""Initialize the switch."""
		super().__init__(coordinator)
		self._child_id: str = child["child_id"]
		self._child_name: str = child.get("name", self._child_id)
		self._attr_name = "Supervision"
		self._attr_unique_id = f"{DOMAIN}_{self._child_id}_supervision"

	@property
	def device_info(self) -> DeviceInfo:
		"""Return device information for the supervised child."""
		return DeviceInfo(
			identifiers={(DOMAIN, self._child_id)},
			name=self._child_name,
			manufacturer="Google",
			model="Supervised Child",
			entry_type=DeviceEntryType.SERVICE,
			configuration_url=FAMILYLINK_BASE_URL,
		)

	@property
	def is_on(self) -> bool:
		"""Return True – supervision is always active."""
		return True

	@property
	def available(self) -> bool:
		"""Return True when the last coordinator update succeeded."""
		return self.coordinator.last_update_success

	@property
	def extra_state_attributes(self) -> dict[str, Any]:
		"""Return child metadata as state attributes."""
		attrs: dict[str, Any] = {"child_id": self._child_id}
		if self.coordinator.data:
			# Find the child's current entry to expose email etc.
			for child in self.coordinator.data.get("children", []):
				if child["child_id"] == self._child_id:
					attrs["email"] = child.get("email", "")
					break
		return attrs

	async def async_turn_on(self, **kwargs: Any) -> None:
		"""No-op: supervision cannot be toggled via HA."""
		_LOGGER.warning(
			"Turning on supervision switch for %s is a no-op – supervision is always active.",
			self._child_name,
		)

	async def async_turn_off(self, **kwargs: Any) -> None:
		"""No-op: supervision cannot be disabled via HA."""
		_LOGGER.warning(
			"Turning off supervision switch for %s is not supported – "
			"use the Family Link app to manage parental controls.",
			self._child_name,
		)
