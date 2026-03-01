"""Data update coordinator for Google Family Link integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client.api import FamilyLinkClient
from .client.parsers import parse_restrictions, parse_usage
from .const import (
	CONF_UPDATE_INTERVAL,
	DEFAULT_UPDATE_INTERVAL,
	DOMAIN,
	LOGGER_NAME,
)
from .exceptions import FamilyLinkException, SessionExpiredError, TransientNetworkError

_LOGGER = logging.getLogger(LOGGER_NAME)


# Module-level aliases kept for backwards compatibility / direct imports in tests
_parse_usage = parse_usage
_parse_restrictions = parse_restrictions


class FamilyLinkDataUpdateCoordinator(DataUpdateCoordinator):
	"""Class to manage fetching data from the Family Link API."""

	def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
		"""Initialize the coordinator."""
		self.entry = entry
		self.client: FamilyLinkClient | None = None
		self._children: dict[str, dict[str, Any]] = {}

		# Respect options → data → default fallback for polling interval
		interval = int(
			entry.options.get(
				CONF_UPDATE_INTERVAL,
				entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
			)
		)

		super().__init__(
			hass,
			_LOGGER,
			name=DOMAIN,
			update_interval=timedelta(seconds=interval),
		)

	async def _async_update_data(self) -> dict[str, Any]:
		"""Fetch data for all supervised children in parallel."""
		try:
			if self.client is None:
				await self._async_setup_client()

			# 1. Fetch children list
			children = await self.client.async_get_members()
			self._children = {c["child_id"]: c for c in children}

			# 2. Fetch raw appsandusage for every child in parallel (single call per child)
			usage: dict[str, list[dict[str, Any]]] = {}
			restrictions: dict[str, dict[str, Any]] = {}
			devices: dict[str, list[dict[str, Any]]] = {}

			if children:
				raw_results: list[dict[str, Any] | BaseException] = list(
					await asyncio.gather(
						*[
							self.client.async_get_apps_and_usage(c["child_id"])
							for c in children
						],
						return_exceptions=True,
					)
				)
				for child, result in zip(children, raw_results):
					cid = child["child_id"]
					if isinstance(result, BaseException):
						if isinstance(result, TransientNetworkError):
							_LOGGER.debug(
								"Transient error fetching data for child %s: %s", cid, result
							)
						else:
							_LOGGER.warning(
								"Failed to fetch data for child %s: %s", cid, result
							)
						usage[cid] = []
						restrictions[cid] = {
							"limited": [],
							"blocked": [],
							"always_allowed": [],
						}
					else:
						usage[cid] = parse_usage(result)
						restrictions[cid] = parse_restrictions(result)

				# 3. Fetch per-device time limits, device names and daily limits in parallel
				gather_results = list(
					await asyncio.gather(
						*[
							self.client.async_get_applied_time_limits(c["child_id"])
							for c in children
						],
						*[
							self.client.async_get_device_names(c["child_id"])
							for c in children
						],
						*[
							self.client.async_get_time_limit(c["child_id"])
							for c in children
						],
						return_exceptions=True,
					)
				)
				n = len(children)
				device_results = gather_results[:n]
				name_results = gather_results[n : n * 2]
				daily_results = gather_results[n * 2 :]

				daily_limits: dict[str, dict[int, dict]] = {}
				for child, dev_result, name_result, daily_result in zip(
					children, device_results, name_results, daily_results
				):
					cid = child["child_id"]
					if isinstance(dev_result, BaseException):
						if isinstance(dev_result, TransientNetworkError):
							_LOGGER.debug(
								"Transient error fetching device limits for child %s: %s", cid, dev_result
							)
						else:
							_LOGGER.warning(
								"Failed to fetch device limits for child %s: %s", cid, dev_result
							)
						devices[cid] = []
					else:
						if not dev_result:
							_LOGGER.warning(
								"appliedTimeLimits returned empty list for child %s – "
								"check if JSPB parser is receiving the expected array format",
								cid,
							)
						# Enrich each device entry with its human-readable name
						name_map: dict[str, str] = name_result if isinstance(name_result, dict) else {}
						for dev in dev_result:
							did = dev.get("device_id", "")
							dev["device_name"] = name_map.get(did) or f"…{did[-6:]}"
						devices[cid] = dev_result
					if isinstance(daily_result, BaseException):
						if isinstance(daily_result, TransientNetworkError):
							_LOGGER.debug(
								"Transient error fetching daily limits for child %s: %s", cid, daily_result
							)
						else:
							_LOGGER.warning(
								"Failed to fetch daily limits for child %s: %s", cid, daily_result
							)
						daily_limits[cid] = {}
					else:
						daily_limits[cid] = daily_result
			# If no children, all dicts stay empty

			total_physical_devices = sum(len(v) for v in devices.values())
			if total_physical_devices == 0 and children:
				_LOGGER.warning(
					"No physical devices found for any of %d children – "
					"device cards will not appear in HA. "
					"Enable debug logging (custom_components.familylink) and check for "
					"'appliedTimeLimits raw entry' or 'appliedTimeLimits returned empty list'.",
					len(children),
				)
			else:
				for cid, devs in devices.items():
					_LOGGER.info(
						"Physical devices for child %s: %s",
						cid,
						[d.get("device_name", d.get("device_id", "?")) for d in devs],
					)
			_LOGGER.debug(
				"Updated data: %d children, usage for %d, restrictions for %d, "
				"devices for %d (%d physical), daily_limits for %d",
				len(children),
				len(usage),
				len(restrictions),
				len(devices),
				total_physical_devices,
				len(daily_limits),
			)
			await self._async_persist_cookies()
			return {
				"children": children,
				"usage": usage,
				"restrictions": restrictions,
				"devices": devices,
				"daily_limits": daily_limits,
			}

		except SessionExpiredError:
			_LOGGER.warning("Session expired, attempting to refresh authentication")
			await self._async_refresh_auth()
			raise UpdateFailed("Session expired, please re-authenticate")

		except FamilyLinkException as err:
			# HTTP 401 means Google no longer accepts our stored cookies.
			# Trigger HA's re-authentication UI instead of looping with UpdateFailed.
			if "401" in str(err):
				_LOGGER.warning(
					"HTTP 401 from Family Link API – cookies expired, initiating re-authentication"
				)
				await self._async_refresh_auth()
				raise UpdateFailed("Session expired (HTTP 401), please re-authenticate") from err
			_LOGGER.error("Error fetching Family Link data: %s", err)
			raise UpdateFailed(f"Error communicating with Family Link: {err}") from err

		except Exception as err:
			_LOGGER.exception("Unexpected error fetching Family Link data")
			raise UpdateFailed(f"Unexpected error: {err}") from err

	async def _async_setup_client(self) -> None:
		"""Set up the Family Link client."""
		if self.client is not None:
			return

		try:
			self.client = FamilyLinkClient(
				hass=self.hass,
				config=self.entry.data,
			)
			await self.client.async_authenticate()
			_LOGGER.debug("Successfully set up Family Link client")

		except Exception as err:
			_LOGGER.error("Failed to setup Family Link client: %s", err)
			self.client = None  # ensure next update retries setup
			raise

	async def _async_persist_cookies(self) -> None:
		"""Persist any Set-Cookie renewals back to the config entry.

		Called after every successful update cycle.  If Google returned new
		``Set-Cookie`` headers during the cycle, the updated cookie values are
		merged into the stored list and written back to the config entry so the
		new values survive a Home Assistant restart.
		"""
		if self.client is None:
			return
		try:
			updated = self.client.get_updated_cookies()
		except Exception as err:  # pragma: no cover
			_LOGGER.debug("Cookie persistence skipped: %s", err)
			return
		if not updated:
			return
		new_data = {**self.entry.data, "cookies": updated}
		self.hass.config_entries.async_update_entry(self.entry, data=new_data)
		_LOGGER.debug(
			"Persisted %d cookie(s) back to config entry after auto-renewal",
			len(updated),
		)

	async def _async_refresh_auth(self) -> None:
		"""Trigger re-authentication when the session expires."""
		_LOGGER.warning("Session expired – initiating re-authentication flow")
		self.client = None
		self.entry.async_start_reauth(self.hass)

	# ------------------------------------------------------------------
	# LLM agent tool methods (called by llm_api.py tools)
	# ------------------------------------------------------------------

	async def async_get_members(self) -> list[dict[str, Any]]:
		"""Return supervised children in the family.

		Prefers the cached coordinator data to avoid redundant API calls.
		"""
		if self.data and "children" in self.data:
			return self.data["children"]
		if self.client is None:
			await self._async_setup_client()
		return await self.client.async_get_members()

	async def async_get_app_usage(self, child_id: str) -> list[dict[str, Any]]:
		"""Return today's per-app screen time for a child (from cache if available)."""
		if self.data and "usage" in self.data:
			cached = self.data["usage"].get(child_id)
			if cached is not None:
				return cached
		if self.client is None:
			await self._async_setup_client()
		raw = await self.client.async_get_apps_and_usage(child_id)
		return parse_usage(raw)

	async def async_get_app_restrictions(self, child_id: str) -> dict[str, Any]:
		"""Return current app restrictions for a child (from cache if available)."""
		if self.data and "restrictions" in self.data:
			cached = self.data["restrictions"].get(child_id)
			if cached is not None:
				return cached
		if self.client is None:
			await self._async_setup_client()
		raw = await self.client.async_get_apps_and_usage(child_id)
		return parse_restrictions(raw)

	async def async_set_app_limit(
		self, child_id: str, app_name: str, minutes: int
	) -> None:
		"""Set a daily time limit for an app."""
		if self.client is None:
			await self._async_setup_client()
		await self.client.async_update_app_restriction(
			child_id, app_name, time_limit_minutes=minutes
		)

	async def async_remove_app_limit(self, child_id: str, app_name: str) -> None:
		"""Remove the per-app time limit (set unlimited)."""
		if self.client is None:
			await self._async_setup_client()
		await self.client.async_update_app_restriction(child_id, app_name)

	async def async_set_daily_limit(
		self, child_id: str, day_num: int, quota_mins: int
	) -> None:
		"""Set the persistent daily screen time limit for one day of the week.

		Args:
			child_id:   The supervised child's user ID.
			day_num:    Day number (1=Monday … 7=Sunday).
			quota_mins: New daily limit in minutes.
		"""
		if self.client is None:
			await self._async_setup_client()
		# Resolve entry_id from cached data
		try:
			entry_id: str = self.data["daily_limits"][child_id][day_num]["entry_id"]
		except (KeyError, TypeError) as err:
			raise ValueError(
				f"No daily limit entry found for child {child_id} day {day_num}"
			) from err
		await self.client.async_set_daily_limit(child_id, entry_id, quota_mins)

	async def async_set_device_bonus_time(
		self, child_id: str, device_id: str, bonus_minutes: int
	) -> None:
		"""Grant bonus screen time (or clear overrides) for a device.

		Args:
			child_id:      The supervised child's user ID.
			device_id:     Target device ID (from appliedTimeLimits).
			bonus_minutes: Extra minutes to grant today.
			               Pass ``0`` to clear all active overrides.
		"""
		if self.client is None:
			await self._async_setup_client()
		await self.client.async_set_device_bonus_time(child_id, device_id, bonus_minutes)

	async def async_set_today_limit(
		self, child_id: str, device_id: str, day_num: int, quota_mins: int
	) -> None:
		"""Set a one-time today-only screen time limit for a specific device.

		This is a **temporary override** for the current day only and does
		**NOT** modify the weekly timeLimit schedule.  Corresponds to the
		"Heutiges Limit" button in the Family Link app (action=8,
		timeLimitOverrides:batchCreate – confirmed from HAR capture).

		Args:
			child_id:   The supervised child's user ID.
			device_id:  Target device ID (from appliedTimeLimits).
			day_num:    Current weekday (1=Monday … 7=Sunday, from isoweekday()).
			quota_mins: New daily limit in minutes for today only.
		"""
		if self.client is None:
			await self._async_setup_client()
		try:
			entry_id: str = self.data["daily_limits"][child_id][day_num]["entry_id"]
		except (KeyError, TypeError) as err:
			raise ValueError(
				f"No daily limit entry found for child {child_id} day {day_num} – "
				"ensure the weekly schedule has been fetched at least once"
			) from err
		await self.client.async_set_today_limit(child_id, device_id, entry_id, quota_mins)

	async def async_set_bulk_limit(self, child_id: str, minutes: int) -> None:
		"""Set the same daily time limit for **every** supervisable app of a child.

		All apps in *supervisable* (neither blocked nor always-allowed) receive the
		new limit in a single API call.  Pass ``minutes=0`` to remove all per-app
		limits, leaving apps unrestricted.
		"""
		if self.client is None:
			await self._async_setup_client()

		# Prefer cached supervisable list to avoid an extra API round-trip
		packages: list[str] = []
		if self.data and "restrictions" in self.data:
			packages = [
				s["package"]
				for s in self.data["restrictions"].get(child_id, {}).get("supervisable", [])
				if s.get("package")
			]

		if not packages:
			# Cache miss – fetch fresh data
			raw = await self.client.async_get_apps_and_usage(child_id)
			packages = [
				s["package"]
				for s in parse_restrictions(raw).get("supervisable", [])
				if s.get("package")
			]

		await self.client.async_bulk_update_restrictions(child_id, packages, minutes)

	async def async_block_app(self, child_id: str, app_name: str) -> None:
		"""Block an app for a child."""
		if self.client is None:
			await self._async_setup_client()
		await self.client.async_update_app_restriction(child_id, app_name, block=True)

	async def async_allow_app(self, child_id: str, app_name: str) -> None:
		"""Mark an app as always allowed for a child."""
		if self.client is None:
			await self._async_setup_client()
		await self.client.async_update_app_restriction(child_id, app_name, always_allow=True)

	async def async_cleanup(self) -> None:
		"""Clean up coordinator resources."""
		if self.client is not None:
			await self.client.async_cleanup()
			self.client = None
		_LOGGER.debug("Coordinator cleanup completed")
