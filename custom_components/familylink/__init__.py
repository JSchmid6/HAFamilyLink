"""The Google Family Link integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

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

		# Remove duplicate entity registry entries left by earlier reload loops.
		_async_cleanup_duplicate_entities(hass, entry)

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


def _async_cleanup_duplicate_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
	"""Remove entity registry entries whose unique_id appears more than once.

	Earlier versions (v0.8.7/v0.8.8) had a reload loop that caused the same
	entities to be registered multiple times.  HA keeps those stale entries
	persisted in the entity registry and then rejects the fresh ones with
	"ID already exists".  This cleanup runs once at setup and removes duplicate
	entries so the current setup can register cleanly.
	"""
	registry = er.async_get(hass)
	seen: set[str] = set()
	for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
		uid = entity_entry.unique_id
		if uid in seen:
			_LOGGER.warning(
				"Removing duplicate entity registry entry %s (unique_id=%s)",
				entity_entry.entity_id, uid,
			)
			registry.async_remove(entity_entry.entity_id)
		else:
			seen.add(uid)


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