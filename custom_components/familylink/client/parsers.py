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

	The API returns **JSPB array format** (``application/json+protobuf``), not a
	plain JSON dict.  The outer structure is::

		[[metadata], [[device_entry, ...]]]

	where each ``device_entry`` is a positional array.  Confirmed field indices
	(from HAR capture of familylink.google.com):

	  * ``[6]``  – today's usage quota in minutes (int)
	  * ``[19]`` – screen time used today in milliseconds (string)
	  * ``[25]`` – opaque device ID string
	  * ``[28]`` – is_locked flag (1 = locked, 0 = unlocked)
	  * ``[30]`` – active overrides list (each element: ``[device_ref, action, ...]``)

	Returns:
		List of dicts with keys:
		  - ``device_id``            – opaque Google device ID string
		  - ``is_locked``            – True when device is currently locked
		  - ``active_policy``        – "override" | "timeLimitOn" | "noActivePolicy"
		  - ``override_action``      – integer action code of active override, or None
		  - ``usage_minutes_today``  – screen time used today (minutes, rounded down)
		  - ``today_limit_minutes``  – daily limit in minutes for today, or None
	"""
	import logging as _logging
	_log = _logging.getLogger("custom_components.familylink")

	# ── Detect format ─────────────────────────────────────────────────────────
	# Response is a JSPB positional array: [[metadata], [[entry, ...]]]
	if not isinstance(raw, list) or len(raw) < 2:
		_log.warning(
			"appliedTimeLimits: unexpected response type %s – expected JSPB list",
			type(raw).__name__,
		)
		return []

	entries_wrapper = raw[1]
	if not isinstance(entries_wrapper, list):
		return []

	devices: list[dict[str, Any]] = []

	for entry in entries_wrapper:
		if not isinstance(entry, list):
			continue

		_log.debug("appliedTimeLimits raw entry (len=%d): %s", len(entry), entry)

		# ── device_id ─────────────────────────────────────────────────────────
		device_id: str = entry[25] if len(entry) > 25 and isinstance(entry[25], str) else ""
		if not device_id:
			continue

		# ── is_locked ─────────────────────────────────────────────────────────
		is_locked: bool = bool(entry[28]) if len(entry) > 28 else False

		# ── active_policy / override_action ───────────────────────────────────
		override_action: int | None = None
		overrides = entry[30] if len(entry) > 30 and isinstance(entry[30], list) else []
		if overrides:
			first = overrides[0]
			if isinstance(first, list) and len(first) > 1:
				try:
					override_action = int(first[1])
				except (ValueError, TypeError):
					pass

		if override_action is not None:
			active_policy = "override"
		elif is_locked:
			active_policy = "timeLimitOn"
		else:
			active_policy = "noActivePolicy"

		# ── usage_minutes_today ────────────────────────────────────────────────
		# Index 19: currentUsageUsedMillis as a string (e.g. "5700000")
		usage_minutes = 0
		if len(entry) > 19 and entry[19] is not None:
			try:
				usage_minutes = int(entry[19]) // 60_000
			except (ValueError, TypeError):
				pass

		# ── today_limit_minutes ───────────────────────────────────────────────
		# Index 6: usageQuotaMins as an integer (e.g. 95)
		today_limit: int | None = None
		if len(entry) > 6 and isinstance(entry[6], int):
			today_limit = entry[6]

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

	return devices
