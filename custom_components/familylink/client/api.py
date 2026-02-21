"""API client for Google Family Link integration.

Uses the unofficial kidsmanagement-pa.clients6.google.com endpoint that powers
the families.google.com web app.  Authentication is cookie-based: the SAPISID
cookie from a prior browser login is used to generate a per-request
SAPISIDHASH Authorization header (SHA-1 of ``{timestamp} {sapisid} {origin}``).

Reference implementation: https://github.com/tducret/familylink
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

from ..auth.session import SessionManager
from ..const import (
	CAPABILITY_APP_USAGE,
	CAPABILITY_SUPERVISION,
	DEVICE_LOCK_ACTION,
	DEVICE_UNLOCK_ACTION,
	FAMILYLINK_ORIGIN,
	GOOG_API_KEY,
	KIDSMANAGEMENT_BASE_URL,
	LOGGER_NAME,
)
from ..exceptions import (
	AuthenticationError,
	DeviceControlError,
	NetworkError,
	SessionExpiredError,
)

_LOGGER = logging.getLogger(LOGGER_NAME)

_USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
	"Gecko/20100101 Firefox/133.0"
)


def _sapisidhash(sapisid: str, origin: str) -> str:
	"""Generate the SAPISIDHASH authorization token.

	Format: ``{timestamp_ms}_{sha1(timestamp_ms + ' ' + sapisid + ' ' + origin)}``
	"""
	ts = int(time.time() * 1000)
	digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
	return f"{ts}_{digest}"


class FamilyLinkClient:
	"""Async client for the Google Kids Management API."""

	def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
		"""Initialize the Family Link client."""
		self.hass = hass
		self.config = config
		self.session_manager = SessionManager(hass, config)
		self._session: aiohttp.ClientSession | None = None
		# Cache: child_id → {app_title_lower: package_name}
		self._app_cache: dict[str, dict[str, str]] = {}

	# ------------------------------------------------------------------
	# Auth
	# ------------------------------------------------------------------

	async def async_authenticate(self) -> None:
		"""Load & validate the stored session cookies."""
		session_data = await self.session_manager.async_load_session()
		if not session_data:
			_LOGGER.debug("No session data found – authentication required")
			raise AuthenticationError("Authentication required")
		if not self.session_manager.is_authenticated():
			_LOGGER.debug("Session cookies have expired – re-authentication required")
			raise SessionExpiredError("Session cookies have expired")
		_LOGGER.debug("Using existing authentication session")

	async def async_refresh_session(self) -> None:
		"""Invalidate the current session (triggers re-auth flow in the coordinator)."""
		await self.session_manager.async_clear_session()
		raise SessionExpiredError("Session refresh required")

	# ------------------------------------------------------------------
	# Family members
	# ------------------------------------------------------------------

	async def async_get_members(self) -> list[dict[str, Any]]:
		"""Return all family members, filtered to supervised children."""
		_LOGGER.debug("Fetching family members")
		session = await self._get_session()
		url = f"{KIDSMANAGEMENT_BASE_URL}/families/mine/members"
		headers = {"Content-Type": "application/json", **self._auth_headers()}
		try:
			async with session.get(url, headers=headers) as resp:
				resp.raise_for_status()
				data = await resp.json(content_type=None)
		except aiohttp.ClientResponseError as err:
			_LOGGER.error("Failed to fetch family members: HTTP %s", err.status)
			raise NetworkError(f"HTTP {err.status} while fetching members") from err
		except Exception as err:
			_LOGGER.error("Failed to fetch family members: %s", err)
			raise NetworkError(f"Failed to fetch members: {err}") from err

		members: list[dict[str, Any]] = []
		for m in data.get("members", []):
			sup_info = m.get("memberSupervisionInfo", {})
			if not sup_info.get("isSupervisedMember", False):
				continue
			profile = m.get("profile", {})
			members.append(
				{
					"child_id": m.get("userId", ""),
					"name": profile.get("displayName", ""),
					"email": profile.get("email", ""),
				}
			)
		_LOGGER.debug("Found %d supervised children", len(members))
		return members

	# ------------------------------------------------------------------
	# Apps & usage
	# ------------------------------------------------------------------

	async def async_get_apps_and_usage(self, child_id: str) -> dict[str, Any]:
		"""Fetch apps, restrictions and today's usage for one child."""
		_LOGGER.debug("Fetching apps & usage for child %s", child_id)
		session = await self._get_session()
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/appsandusage"
		params = {"capabilities": [CAPABILITY_APP_USAGE, CAPABILITY_SUPERVISION]}
		headers = {"Content-Type": "application/json", **self._auth_headers()}
		try:
			async with session.get(url, headers=headers, params=params) as resp:
				resp.raise_for_status()
				data = await resp.json(content_type=None)
		except aiohttp.ClientResponseError as err:
			_LOGGER.error("Failed to fetch app usage [child=%s]: HTTP %s", child_id, err.status)
			raise NetworkError(f"HTTP {err.status} while fetching app usage") from err
		except Exception as err:
			_LOGGER.error("Failed to fetch app usage [child=%s]: %s", child_id, err)
			raise NetworkError(f"Failed to fetch app usage: {err}") from err

		# Update app title→package cache for this child
		cache: dict[str, str] = {}
		for app in data.get("apps", []):
			title = app.get("title", "")
			pkg = app.get("packageName", "")
			if title and pkg:
				cache[title.lower()] = pkg
		self._app_cache[child_id] = cache

		return data

	# ------------------------------------------------------------------
	# App restriction control
	# ------------------------------------------------------------------

	async def async_update_app_restriction(
		self,
		child_id: str,
		app_name: str,
		*,
		block: bool = False,
		always_allow: bool = False,
		time_limit_minutes: int | None = None,
	) -> None:
		"""Update restrictions for a single app.

		Exactly one of ``block``, ``always_allow``, or ``time_limit_minutes`` must
		be specified.  Pass none of them (all defaults) to remove a time limit.
		"""
		if sum([block, always_allow, time_limit_minutes is not None]) > 1:
			raise ValueError("Specify exactly one of: block, always_allow, time_limit_minutes")

		pkg = await self._resolve_package(child_id, app_name)
		_LOGGER.debug(
			"Updating restriction for %s (pkg=%s) [child=%s]: block=%s always_allow=%s minutes=%s",
			app_name, pkg, child_id, block, always_allow, time_limit_minutes,
		)

		if block:
			restriction = [[pkg], [1]]
		elif always_allow:
			restriction = [[pkg], None, None, [1]]
		elif time_limit_minutes is not None:
			restriction = [[pkg], None, [time_limit_minutes, 1]]
		else:
			# Remove limit – set empty restriction
			restriction = [[pkg]]

		payload = json.dumps([child_id, [restriction]])
		session = await self._get_session()
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/apps:updateRestrictions"
		headers = {
			"Content-Type": "application/json+protobuf",
			**self._auth_headers(),
		}
		try:
			async with session.post(url, data=payload, headers=headers) as resp:
				resp.raise_for_status()
		except aiohttp.ClientResponseError as err:
			_LOGGER.error(
				"Failed to update restriction for %s [child=%s]: HTTP %s",
				app_name, child_id, err.status,
			)
			raise DeviceControlError(
				f"HTTP {err.status} while updating restriction for '{app_name}'"
			) from err
		except Exception as err:
			_LOGGER.error("Failed to update restriction for %s: %s", app_name, err)
			raise DeviceControlError(f"Failed to update restriction: {err}") from err

	# ------------------------------------------------------------------
	# Cleanup
	# ------------------------------------------------------------------

	async def async_cleanup(self) -> None:
		"""Close the underlying aiohttp session."""
		if self._session:
			await self._session.close()
			self._session = None

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _auth_headers(self) -> dict[str, str]:
		"""Build fresh per-request authentication headers."""
		sapisid = self._get_sapisid()
		return {
			"Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, FAMILYLINK_ORIGIN)}",
			"Origin": FAMILYLINK_ORIGIN,
			"X-Goog-Api-Key": GOOG_API_KEY,
		}

	def _get_sapisid(self) -> str:
		"""Extract the SAPISID cookie value from the stored session."""
		try:
			cookies = self.session_manager.get_cookies()
		except SessionExpiredError:
			raise AuthenticationError("No active session – please re-authenticate")

		for c in cookies:
			if c.get("name") == "SAPISID" and ".google.com" in c.get("domain", ""):
				return c["value"]

		# Some browsers export __Secure-3PAPISID instead – fall back to that
		for c in cookies:
			if c.get("name") in ("__Secure-3PAPISID", "APISID"):
				return c["value"]

		raise AuthenticationError(
			"SAPISID cookie not found – please re-authenticate via the integration options."
		)

	async def _get_session(self) -> aiohttp.ClientSession:
		"""Return (or lazily create) the shared aiohttp session."""
		if self._session is None or self._session.closed:
			cookies: dict[str, str] = {}
			try:
				for c in self.session_manager.get_cookies():
					cookies[c["name"]] = c["value"]
			except Exception as err:
				_LOGGER.warning("Could not load cookies for HTTP session: %s", err)

			self._session = aiohttp.ClientSession(
				cookies=cookies,
				headers={"User-Agent": _USER_AGENT},
				timeout=aiohttp.ClientTimeout(total=30),
			)
		return self._session

	async def _resolve_package(self, child_id: str, app_name: str) -> str:
		"""Resolve an app title or package name to an Android package name.

		If *app_name* already looks like a package name (contains a dot) it is
		returned as-is.  Otherwise the app cache is populated (if empty) and a
		case-insensitive title lookup is performed.
		"""
		if "." in app_name:
			return app_name  # already a package name

		if child_id not in self._app_cache:
			await self.async_get_apps_and_usage(child_id)

		cache = self._app_cache.get(child_id, {})
		pkg = cache.get(app_name.lower())
		if not pkg:
			raise DeviceControlError(
				f"App '{app_name}' not found on child's device. "
				"Check the exact name (case-sensitive) or use the Android package name."
			)
		return pkg

	# ------------------------------------------------------------------
	# Legacy device control (kept for switch platform compatibility)
	# ------------------------------------------------------------------

	async def async_get_devices(self) -> list[dict[str, Any]]:
		"""Return supervised children as 'devices' (used by switch platform)."""
		members = await self.async_get_members()
		return [
			{
				"id": m["child_id"],
				"name": m["name"],
				"email": m["email"],
				"locked": False,
				"type": "supervised_child",
			}
			for m in members
		]

	async def async_control_device(self, device_id: str, action: str) -> bool:
		"""Legacy device control stub – not used by LLM tools."""
		if action not in [DEVICE_LOCK_ACTION, DEVICE_UNLOCK_ACTION]:
			raise DeviceControlError(f"Invalid action: {action}")
		_LOGGER.warning(
			"async_control_device called with action=%s for device=%s – not implemented",
			action, device_id,
		)
		return False

		return self._session 