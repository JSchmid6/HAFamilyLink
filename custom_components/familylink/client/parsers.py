"""Pure data-transformation helpers for the kidsmanagement API responses.

These functions have **no** Home Assistant imports so they can be unit-tested
without an HA installation present.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any


def parse_usage(raw: dict[str, Any]) -> list[dict[str, Any]]:
	"""Parse per-app screen-time sessions for *today* from a raw appsandusage response.

	Returns a list of ``{app_name, usage_seconds}`` dicts sorted by usage
	descending.
	"""
	today = _date.today()

	# Build package → title map from the apps list
	pkg_to_title: dict[str, str] = {
		app.get("packageName", ""): app.get("title", "")
		for app in raw.get("apps", [])
		if app.get("packageName") and app.get("title")
	}

	usage_list: list[dict[str, Any]] = []
	for session in raw.get("appUsageSessions", []):
		d = session.get("date", {})
		if (
			d.get("year") == today.year
			and d.get("month") == today.month
			and d.get("day") == today.day
		):
			raw_dur = session.get("usage", "0s").rstrip("s")
			try:
				seconds = float(raw_dur)
				# Guard against NaN (float('nan') != float('nan'))
				if seconds != seconds:
					seconds = 0.0
			except ValueError:
				seconds = 0.0
			pkg = session.get("appId", {}).get("androidAppPackageName", "")
			app_title = pkg_to_title.get(pkg, pkg)
			usage_list.append({"app_name": app_title, "usage_seconds": int(seconds)})

	usage_list.sort(key=lambda x: x["usage_seconds"], reverse=True)
	return usage_list


def parse_restrictions(raw: dict[str, Any]) -> dict[str, Any]:
	"""Parse app restriction settings from a raw appsandusage response.

	Returns a dict with keys:
	  - ``limited``        – apps that have a per-app daily time limit
	  - ``blocked``        – apps that are entirely hidden/blocked
	  - ``always_allowed`` – apps explicitly marked as always allowed
	  - ``supervisable``   – all apps that *can* have a time limit and are
	                         neither blocked nor always-allowed (includes limited
	                         ones); used for bulk-limit operations.
	"""
	limited: list[dict[str, Any]] = []
	blocked: list[str] = []
	always_allowed: list[str] = []
	supervisable: list[dict[str, str]] = []

	for app in raw.get("apps", []):
		title = app.get("title", app.get("packageName", ""))
		pkg = app.get("packageName", "")
		settings = app.get("supervisionSetting", {})
		caps = app.get("supervisionCapabilities", [])
		can_limit = "capabilityUsageLimit" in caps

		is_blocked = settings.get("hidden", False)
		is_always_allowed = (
			settings.get("alwaysAllowedAppInfo", {}).get("alwaysAllowedState")
			== "alwaysAllowedStateEnabled"
		)

		if is_blocked:
			blocked.append(title)
		elif (limit := settings.get("usageLimit")):
			limited.append({"app": title, "limit_minutes": limit.get("dailyUsageLimitMins"), "package": pkg})
		elif is_always_allowed:
			always_allowed.append(title)

		# All non-blocked, non-always-allowed apps capable of a time limit
		if can_limit and not is_blocked and not is_always_allowed:
			supervisable.append({"package": pkg, "title": title})

	return {
		"limited": limited,
		"blocked": blocked,
		"always_allowed": always_allowed,
		"supervisable": supervisable,
	}


def parse_applied_time_limits(raw: Any) -> list[dict[str, Any]]:
	"""Parse the appliedTimeLimits response into a flat list of device dicts.

	The API has returned two different formats over time:

	**New format (JSON dict – current as of 2026):**

	.. code-block:: json

		{
		  "appliedTimeLimits": [
		    {
		      "deviceId": "aannnpp...",
		      "isLocked": false,
		      "activePolicy": "noActivePolicy",
		      "currentUsageUsedMillis": "3639340",
		      "currentUsageLimitEntry": {"usageQuotaMins": 95, ...}
		    }
		  ]
		}

	**Old format (JSPB positional array – pre-2026):**

	.. code-block:: python

		[[metadata], [[entry0, entry1, ...]]]

	where each entry is a positional array with device_id at index 25.

	Returns:
		List of dicts with keys:
		  - ``device_id``            – opaque Google device ID string
		  - ``is_locked``            – True when device is currently locked
		  - ``active_policy``        – "override" | "usageLimit" | "noActivePolicy" | ...
		  - ``override_action``      – integer action code of active override, or None
		  - ``usage_minutes_today``  – screen time used today (minutes, rounded down)
		  - ``today_limit_minutes``  – daily limit in minutes for today, or None
	"""
	import logging as _logging
	_log = _logging.getLogger("custom_components.familylink")

	# ── New JSON-dict format (current API) ────────────────────────────────────
	if isinstance(raw, dict):
		entries = raw.get("appliedTimeLimits", [])
		if not isinstance(entries, list):
			_log.warning(
				"appliedTimeLimits dict response has no 'appliedTimeLimits' list – "
				"got type=%s. Physical devices will not appear in HA.",
				type(entries).__name__,
			)
			return []

		devices: list[dict[str, Any]] = []
		for entry in entries:
			if not isinstance(entry, dict):
				continue

			device_id: str = entry.get("deviceId", "")
			if not device_id:
				_log.warning("appliedTimeLimits entry missing 'deviceId': %s", entry)
				continue

			is_locked: bool = bool(entry.get("isLocked", False))
			active_policy: str = entry.get("activePolicy", "noActivePolicy")

			# Override action not directly exposed in new format; infer from policy
			override_action: int | None = None

			# Usage today: "currentUsageUsedMillis" is a millisecond string
			usage_minutes = 0
			raw_used = entry.get("currentUsageUsedMillis")
			if raw_used is not None:
				try:
					usage_minutes = int(raw_used) // 60_000
				except (ValueError, TypeError):
					pass

			# Today's limit: usageQuotaMins inside currentUsageLimitEntry
			today_limit: int | None = None
			limit_entry = entry.get("currentUsageLimitEntry", {})
			if isinstance(limit_entry, dict):
				quota = limit_entry.get("usageQuotaMins")
				if isinstance(quota, int):
					today_limit = quota

			devices.append(
				{
					"device_id": device_id,
					"is_locked": is_locked,
					"active_policy": active_policy,
					"override_action": override_action,
					"usage_minutes_today": usage_minutes,
					"today_limit_minutes": today_limit,
				}
			)

		if devices:
			_log.debug(
				"appliedTimeLimits (JSON dict): parsed %d device(s): %s",
				len(devices),
				[d["device_id"] for d in devices],
			)
		else:
			_log.warning(
				"appliedTimeLimits (JSON dict): 0 devices parsed from %d entries. "
				"Raw response: %s",
				len(entries),
				entries,
			)
		return devices

	# ── Legacy JSPB positional-array format (pre-2026) ────────────────────────
	if isinstance(raw, list) and len(raw) >= 2:
		_log.debug("appliedTimeLimits: received legacy JSPB list format – parsing positionally")
		entries_wrapper = raw[1]
		if not isinstance(entries_wrapper, list):
			_log.warning(
				"appliedTimeLimits (JSPB): raw[1] is not a list – type=%s. "
				"Physical devices will not appear in HA.",
				type(entries_wrapper).__name__,
			)
			return []

		devices_jspb: list[dict[str, Any]] = []
		for entry in entries_wrapper:
			if not isinstance(entry, list):
				continue
			_log.debug("appliedTimeLimits JSPB entry (len=%d): %s", len(entry), entry)

			device_id = entry[25] if len(entry) > 25 and isinstance(entry[25], str) else ""
			if not device_id:
				_log.warning(
					"appliedTimeLimits (JSPB) entry skipped: no device_id at index 25 "
					"(len=%d, index-25=%r). Entry: %s",
					len(entry),
					entry[25] if len(entry) > 25 else "<missing>",
					entry,
				)
				continue

			is_locked_j: bool = bool(entry[28]) if len(entry) > 28 else False
			override_action_j: int | None = None
			overrides = entry[30] if len(entry) > 30 and isinstance(entry[30], list) else []
			if overrides:
				first = overrides[0]
				if isinstance(first, list) and len(first) > 1:
					try:
						override_action_j = int(first[1])
					except (ValueError, TypeError):
						pass

			if override_action_j is not None:
				active_policy_j = "override"
			elif is_locked_j:
				active_policy_j = "timeLimitOn"
			else:
				active_policy_j = "noActivePolicy"

			usage_minutes_j = 0
			if len(entry) > 19 and entry[19] is not None:
				try:
					usage_minutes_j = int(entry[19]) // 60_000
				except (ValueError, TypeError):
					pass

			today_limit_j: int | None = None
			if len(entry) > 6 and isinstance(entry[6], int):
				today_limit_j = entry[6]

			devices_jspb.append(
				{
					"device_id": device_id,
					"is_locked": is_locked_j,
					"active_policy": active_policy_j,
					"override_action": override_action_j,
					"usage_minutes_today": usage_minutes_j,
					"today_limit_minutes": today_limit_j,
				}
			)

		if devices_jspb:
			_log.debug(
				"appliedTimeLimits (JSPB): parsed %d device(s): %s",
				len(devices_jspb),
				[d["device_id"] for d in devices_jspb],
			)
		else:
			_log.warning(
				"appliedTimeLimits (JSPB): 0 devices from %d entries. "
				"First entry: %s",
				len(entries_wrapper),
				entries_wrapper[0] if entries_wrapper else "<empty>",
			)
		return devices_jspb

	# ── Unknown format ────────────────────────────────────────────────────────
	_log.warning(
		"appliedTimeLimits: unrecognised response type=%s. "
		"Physical devices will not appear in HA. Value: %r",
		type(raw).__name__,
		raw,
	)
	return []
