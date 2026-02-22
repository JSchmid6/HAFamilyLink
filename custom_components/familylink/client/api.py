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
from .parsers import parse_applied_time_limits
from ..const import (
	CAPABILITY_APP_USAGE,
	CAPABILITY_SUPERVISION,
	CAPABILITY_TIME_LIMITS,
	DEVICE_LOCK_ACTION,
	DEVICE_UNLOCK_ACTION,
	FAMILYLINK_ORIGIN,
	GOOG_API_KEY,
	GOOG_EXT_BIN_202,
	GOOG_EXT_BIN_223,
	KIDSMANAGEMENT_BASE_URL,
	LOGGER_NAME,
	OVERRIDE_ACTION_BONUS,
	OVERRIDE_ACTION_CLEAR,
	OVERRIDE_ACTION_TODAY_LIMIT,
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

	async def async_bulk_update_restrictions(
		self,
		child_id: str,
		packages: list[str],
		minutes: int,
	) -> None:
		"""Set (or remove) a daily time limit for multiple apps in **one** API call.

		Args:
			child_id:  The supervised child's user ID.
			packages:  List of Android package name strings.
			minutes:   Daily limit in minutes.  Pass ``0`` to remove all limits.
		"""
		if not packages:
			_LOGGER.debug("async_bulk_update_restrictions: empty package list, nothing to do")
			return

		restrictions: list[Any] = []
		for pkg in packages:
			if minutes > 0:
				restrictions.append([[pkg], None, [minutes, 1]])
			else:
				restrictions.append([[pkg]])  # Remove limit

		_LOGGER.debug(
			"Bulk-updating %d app restrictions for child %s (minutes=%s)",
			len(packages), child_id, minutes,
		)
		payload = json.dumps([child_id, restrictions])
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
				"Bulk restriction update failed [child=%s]: HTTP %s", child_id, err.status
			)
			raise DeviceControlError(
				f"HTTP {err.status} while bulk-updating restrictions"
			) from err
		except Exception as err:
			_LOGGER.error("Bulk restriction update failed [child=%s]: %s", child_id, err)
			raise DeviceControlError(f"Failed to bulk-update restrictions: {err}") from err

	# ------------------------------------------------------------------
	# Device time limits (appliedTimeLimits)
	# ------------------------------------------------------------------

	async def async_get_applied_time_limits(
		self, child_id: str
	) -> list[dict[str, Any]]:
		"""Return per-device screen time data for a supervised child.

		Calls ``GET /people/{child_id}/appliedTimeLimits`` and returns a parsed
		list – one dict per physical device – containing:
		  - ``device_id``           – Google device ID string
		  - ``is_locked``           – True when device is currently locked
		  - ``active_policy``       – current policy state
		  - ``override_action``     – action name of active override, or None
		  - ``usage_minutes_today`` – screen time used today in minutes
		  - ``today_limit_minutes`` – daily usage quota in minutes, or None
		"""
		_LOGGER.debug("Fetching applied time limits for child %s", child_id)
		session = await self._get_session()
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/appliedTimeLimits"
		headers = {
			"Content-Type": "application/json",
			**self._auth_headers(),
		}
		params = {"capabilities": CAPABILITY_TIME_LIMITS}
		try:
			async with session.get(url, headers=headers, params=params) as resp:
				resp.raise_for_status()
				data = await resp.json(content_type=None)
		except aiohttp.ClientResponseError as err:
			_LOGGER.error(
				"Failed to fetch applied time limits [child=%s]: HTTP %s", child_id, err.status
			)
			raise NetworkError(
				f"HTTP {err.status} while fetching applied time limits"
			) from err
		except Exception as err:
			_LOGGER.error("Failed to fetch applied time limits [child=%s]: %s", child_id, err)
			raise NetworkError(f"Failed to fetch applied time limits: {err}") from err

		return parse_applied_time_limits(data)

	async def async_set_device_bonus_time(
		self,
		child_id: str,
		device_id: str,
		bonus_minutes: int,
	) -> None:
		"""Grant bonus screen time (or clear overrides) for a specific device.

		Uses ``POST /people/{child_id}/timeLimitOverrides:batchCreate`` with
		JSPB encoding (``json+protobuf`` content-type).

		Args:
			child_id:      The supervised child's user ID.
			device_id:     Target device ID (from appliedTimeLimits).
			bonus_minutes: Extra minutes to grant today.
			               Pass ``0`` to clear all active overrides.

		.. note::
			``action=2`` (OVERRIDE_ACTION_BONUS) with bonus_minutes at JSPB field 6
			was confirmed as HTTP 200 in API probes.  The semantic mapping to
			"add bonus time" is inferred; ``action=3`` for clear is confirmed.
		"""
		if bonus_minutes > 0:
			override_entry = [None, None, OVERRIDE_ACTION_BONUS, device_id, None, bonus_minutes]
		else:
			override_entry = [None, None, OVERRIDE_ACTION_CLEAR, device_id]

		payload = json.dumps([None, None, [override_entry]])
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/timeLimitOverrides:batchCreate"
		headers = {
			"Content-Type": "application/json+protobuf",
			"x-goog-ext-223261916-bin": GOOG_EXT_BIN_223,
			"x-goog-ext-202964622-bin": GOOG_EXT_BIN_202,
			**self._auth_headers(),
		}
		session = await self._get_session()
		_LOGGER.debug(
			"Setting device bonus time: child=%s device=%s minutes=%s",
			child_id, device_id, bonus_minutes,
		)
		try:
			async with session.post(url, data=payload, headers=headers) as resp:
				resp.raise_for_status()
		except aiohttp.ClientResponseError as err:
			_LOGGER.error(
				"Failed to set device bonus time [child=%s device=%s]: HTTP %s",
				child_id, device_id, err.status,
			)
			raise DeviceControlError(
				f"HTTP {err.status} while setting device bonus time"
			) from err
		except Exception as err:
			_LOGGER.error("Failed to set device bonus time: %s", err)
			raise DeviceControlError(f"Failed to set device bonus time: {err}") from err

	async def async_set_today_limit(
		self,
		child_id: str,
		device_id: str,
		entry_id: str,
		quota_mins: int,
	) -> None:
		"""Set a one-time today-only screen time limit for a specific device.

		Uses ``POST /people/{child_id}/timeLimitOverrides:batchCreate`` with
		``action=8`` – confirmed from HAR capture.  This is a **temporary override**
		for the current day only and does **NOT** modify the weekly timeLimit schedule.

		Confirmed JSPB body format (148 bytes, action=8)::

			[null, child_id,
			 [[null,null,8,device_id,null,null,null,null,null,null,null,[2,quota_mins,entry_id]]],
			 [1]]

		where ``entry_id`` is the weekday entry ID from the timeLimit schedule
		(e.g. ``"CAEQBw"`` for Sunday).

		Args:
			child_id:   The supervised child's user ID.
			device_id:  Target device ID (full string from appliedTimeLimits).
			entry_id:   Weekday entry ID from the timeLimit schedule for today.
			quota_mins: New daily limit in minutes for today only.
		"""
		override_entry = [
			None, None, OVERRIDE_ACTION_TODAY_LIMIT, device_id,
			None, None, None, None, None, None, None,
			[2, quota_mins, entry_id],
		]
		payload = json.dumps([None, child_id, [[override_entry]], [1]])
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/timeLimitOverrides:batchCreate"
		headers = {
			"Content-Type": "application/json+protobuf",
			"x-goog-ext-223261916-bin": GOOG_EXT_BIN_223,
			"x-goog-ext-202964622-bin": GOOG_EXT_BIN_202,
			**self._auth_headers(),
		}
		session = await self._get_session()
		_LOGGER.debug(
			"Setting today's limit: child=%s device=%s entry=%s quota=%s min",
			child_id, device_id, entry_id, quota_mins,
		)
		try:
			async with session.post(url, data=payload, headers=headers) as resp:
				resp.raise_for_status()
		except aiohttp.ClientResponseError as err:
			_LOGGER.error(
				"Failed to set today's limit [child=%s device=%s]: HTTP %s",
				child_id, device_id, err.status,
			)
			raise DeviceControlError(
				f"HTTP {err.status} while setting today's limit"
			) from err
		except Exception as err:
			_LOGGER.error("Failed to set today's limit: %s", err)
			raise DeviceControlError(f"Failed to set today's limit: {err}") from err

	# ------------------------------------------------------------------
	# Daily time limits (timeLimit)
	# ------------------------------------------------------------------

	async def async_get_time_limit(self, child_id: str) -> dict[int, dict[str, Any]]:
		"""GET /people/{child_id}/timeLimit → day_num → {entry_id, quota_mins}.

		JSPB structure (confirmed from DevTools):
		  data[1][1][0][2] = list of [entry_id, day_num, type, quota_mins, created_ts, modified_ts]
		Day numbers: 1=Monday … 7=Sunday.
		"""
		_LOGGER.debug("Fetching daily time limits for child %s", child_id)
		session = await self._get_session()
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/timeLimit"
		headers = {
			"Content-Type": "application/json+protobuf",
			"x-goog-ext-223261916-bin": GOOG_EXT_BIN_223,
			"x-goog-ext-202964622-bin": GOOG_EXT_BIN_202,
			**self._auth_headers(),
		}
		try:
			async with session.get(url, headers=headers) as resp:
				resp.raise_for_status()
				raw = await resp.text()
		except aiohttp.ClientResponseError as err:
			_LOGGER.error("Failed to fetch time limits [child=%s]: HTTP %s", child_id, err.status)
			raise NetworkError(f"HTTP {err.status} while fetching time limits") from err
		except Exception as err:
			_LOGGER.error("Failed to fetch time limits [child=%s]: %s", child_id, err)
			raise NetworkError(f"Failed to fetch time limits: {err}") from err

		try:
			data = json.loads(raw)
			entries = data[1][1][0][2]
		except (IndexError, TypeError, KeyError, json.JSONDecodeError) as err:
			_LOGGER.warning("Unexpected timeLimit JSPB structure for child %s: %s", child_id, err)
			return {}

		result: dict[int, dict[str, Any]] = {}
		for entry in entries:
			try:
				entry_id: str = entry[0]
				day_num: int = entry[1]
				quota_mins: int = entry[3]
				result[day_num] = {"entry_id": entry_id, "quota_mins": quota_mins}
			except (IndexError, TypeError):
				continue
		_LOGGER.debug("Daily limits for child %s: %s", child_id, result)
		return result

	async def async_set_daily_limit(
		self,
		child_id: str,
		entry_id: str,
		quota_mins: int,
	) -> None:
		"""PUT /people/{child_id}/timeLimit – set persistent daily screen time limit.

		Confirmed PUT body format (78 bytes for a single entry):
		  [null, child_id, [null, [[2, null, null, [[entry_id, quota_mins]]]]], null, [1]]
		"""
		body = json.dumps(
			[None, child_id, [None, [[2, None, None, [[entry_id, quota_mins]]]]], None, [1]],
			separators=(",", ":"),
		)
		url = f"{KIDSMANAGEMENT_BASE_URL}/people/{child_id}/timeLimit:update"
		headers = {
			"Content-Type": "application/json+protobuf",
			"x-goog-ext-223261916-bin": GOOG_EXT_BIN_223,
			"x-goog-ext-202964622-bin": GOOG_EXT_BIN_202,
			**self._auth_headers(),
		}
		session = await self._get_session()
		_LOGGER.debug(
			"Setting daily limit: child=%s entry_id=%s quota=%s min",
			child_id, entry_id, quota_mins,
		)
		try:
			async with session.post(
				url, data=body, headers=headers, params={"$httpMethod": "PUT"}
			) as resp:
				resp.raise_for_status()
		except aiohttp.ClientResponseError as err:
			_LOGGER.error(
				"Failed to set daily limit [child=%s entry=%s]: HTTP %s",
				child_id, entry_id, err.status,
			)
			raise DeviceControlError(
				f"HTTP {err.status} while setting daily limit"
			) from err
		except Exception as err:
			_LOGGER.error("Failed to set daily limit: %s", err)
			raise DeviceControlError(f"Failed to set daily limit: {err}") from err

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
		"""Build fresh per-request authentication headers.

		Cookies are injected as an explicit ``Cookie`` header rather than being
		managed by the aiohttp CookieJar.  This avoids domain-matching issues
		when the stored cookies (domain ``.google.com``) are sent to
		``kidsmanagement-pa.clients6.google.com``.
		"""
		sapisid = self._get_sapisid()
		try:
			cookie_parts = [
				f"{c['name']}={c['value']}"
				for c in self.session_manager.get_cookies()
			]
			cookie_header = "; ".join(cookie_parts)
		except Exception:
			cookie_header = ""
		headers = {
			"Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, FAMILYLINK_ORIGIN)}",
			"Origin": FAMILYLINK_ORIGIN,
			"X-Goog-Api-Key": GOOG_API_KEY,
		}
		if cookie_header:
			headers["Cookie"] = cookie_header
		return headers

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
		"""Return (or lazily create) the shared aiohttp session.

		Cookies are NOT stored in the session CookieJar – they are injected as
		an explicit ``Cookie`` header in every request via ``_auth_headers()``.
		"""
		if self._session is None or self._session.closed:
			self._session = aiohttp.ClientSession(
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