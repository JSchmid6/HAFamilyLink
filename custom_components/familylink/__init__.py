"""The Google Family Link integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, LOGGER_NAME
from .coordinator import FamilyLinkDataUpdateCoordinator
from .exceptions import FamilyLinkException
from .llm_api import async_register_llm_api

_LOGGER = logging.getLogger(LOGGER_NAME)

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Set up Google Family Link from a config entry."""
	_LOGGER.debug("Setting up Family Link integration")

	try:
		# Create coordinator for data updates
		coordinator = FamilyLinkDataUpdateCoordinator(hass, entry)
		
		# Perform initial data fetch
		await coordinator.async_config_entry_first_refresh()
		
		# Store coordinator in hass data
		hass.data.setdefault(DOMAIN, {})
		hass.data[DOMAIN][entry.entry_id] = coordinator

		# Migrate entity registry: remove entries that are still associated with a
		# child-profile device so they re-register under the physical device.
		_async_migrate_entity_registry(hass, entry, coordinator)

		# Forward setup to platforms
		await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

		# Register LLM agent skills (tools) for conversation agents
		async_register_llm_api(hass, entry)

		# Reload only when *options* genuinely change (e.g. polling interval).
		# async_update_entry also fires the listener for data-only writes such as
		# cookie auto-renewal – those must NOT trigger a reload.
		_options_snapshot = dict(entry.options)

		async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
			if dict(entry.options) != _options_snapshot:
				_LOGGER.debug("Options changed – reloading Family Link entry")
				await async_reload_entry(hass, entry)
			else:
				_LOGGER.debug("Entry data updated (cookie renewal) – skipping reload")

		entry.async_on_unload(entry.add_update_listener(_async_options_updated))

		_LOGGER.info("Successfully set up Family Link integration")
		return True

	except FamilyLinkException as err:
		_LOGGER.error("Failed to set up Family Link: %s", err)
		raise ConfigEntryNotReady from err
	except Exception as err:
		_LOGGER.exception("Unexpected error setting up Family Link: %s", err)
		raise ConfigEntryNotReady from err


def _async_migrate_entity_registry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	coordinator: FamilyLinkDataUpdateCoordinator,
) -> None:
	"""Migrate entity registry entries to the correct device.

	Before v0.8.6, app-limit and weekly-plan entities were registered under the
	child-profile virtual device.  From v0.8.6 onward they live under the
	physical Android device.  HA stores device associations persistently in the
	entity registry and does NOT update them when an entity re-registers with a
	different device_info.  We therefore remove the stale entries so they
	re-register fresh with the correct device.

	Also removes duplicate unique_id entries created by the v0.8.7/v0.8.8 reload
	loop.
	"""
	if not coordinator.data:
		return

	# Collect child profile device identifiers (these are the "wrong" devices)
	children: list[dict] = coordinator.data.get("children", [])
	child_ids: set[str] = {c["child_id"] for c in children}

	# Collect physical device IDs so we know what "right" looks like
	devices_map: dict = coordinator.data.get("devices", {})
	physical_device_ids: set[str] = {
		dev["device_id"]
		for devs in devices_map.values()
		for dev in devs
		if dev.get("device_id")
	}

	if not physical_device_ids:
		# No physical devices known yet – skip migration
		return

	ent_registry = er.async_get(hass)
	dev_registry = dr.async_get(hass)
	seen_uids: set[str] = set()
	removed = 0

	for entity_entry in er.async_entries_for_config_entry(ent_registry, entry.entry_id):
		uid = entity_entry.unique_id

		# Remove duplicates (keep first occurrence)
		if uid in seen_uids:
			ent_registry.async_remove(entity_entry.entity_id)
			removed += 1
			continue
		seen_uids.add(uid)

		# Check if this entity is under a child-profile device
		if not entity_entry.device_id:
			continue
		device = dev_registry.async_get(entity_entry.device_id)
		if not device:
			continue
		device_domains = {ident[0] for ident in device.identifiers}
		device_keys = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
		if DOMAIN in device_domains and device_keys & child_ids:
			# This entity is under a child-profile device → remove so it
			# re-registers under the physical device
			_LOGGER.info(
				"Migrating entity %s from child-profile device to physical device",
				entity_entry.entity_id,
			)
			ent_registry.async_remove(entity_entry.entity_id)
			removed += 1

	if removed:
		_LOGGER.info(
			"Entity registry migration: removed %d stale entries; they will "
			"re-register under the correct physical device",
			removed,
		)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
	"""Unload a config entry."""
	_LOGGER.debug("Unloading Family Link integration")

	# Unload platforms
	unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

	if unload_ok:
		# Remove coordinator from hass data
		coordinator = hass.data[DOMAIN].pop(entry.entry_id)
		
		# Clean up coordinator resources
		if hasattr(coordinator, 'async_cleanup'):
			await coordinator.async_cleanup()

	return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Reload config entry."""
	await async_unload_entry(hass, entry)
	await async_setup_entry(hass, entry) 