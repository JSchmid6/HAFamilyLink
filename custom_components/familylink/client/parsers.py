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


def parse_applied_time_limits(raw: dict[str, Any]) -> list[dict[str, Any]]:
	"""Parse the appliedTimeLimits JSON response into a flat list of device dicts.

	Each entry in ``appliedTimeLimits`` corresponds to one physical device
	supervised under the child account.

	Returns:
		List of dicts with keys:
		  - ``device_id``            – opaque Google device ID string
		  - ``is_locked``            – True when device is currently locked
		  - ``active_policy``        – "override" | "timeLimitOn" | "noActivePolicy"
		  - ``override_action``      – action name from currentOverride, or None
		  - ``usage_minutes_today``  – screen time used today (minutes, rounded down)
		  - ``today_limit_minutes``  – daily limit in minutes for today, or None
	"""
	devices: list[dict[str, Any]] = []
	for entry in raw.get("appliedTimeLimits", []):
		device_id: str = entry.get("deviceId", "")
		if not device_id:
			continue

		is_locked: bool = bool(entry.get("isLocked", False))
		active_policy: str = entry.get("activePolicy", "unknown")

		current_override = entry.get("currentOverride")
		override_action: str | None = (
			current_override.get("action") if isinstance(current_override, dict) else None
		)

		# Screen time used today (API provides milliseconds as string)
		usage_ms_raw = entry.get("currentUsageUsedMillis", "0") or "0"
		try:
			usage_minutes = int(usage_ms_raw) // 60_000
		except (ValueError, TypeError):
			usage_minutes = 0

		# Today's daily quota.
		# Field name varies by API call path; try most-specific first.
		# "nextUsageLimitEntry" is intentionally excluded: it holds *tomorrow's* plan
		# and causes an off-by-one when today's entry is absent (e.g. Sunday with
		# no scheduled limit).
		today_limit: int | None = None
		for limit_key in (
			"currentUsageLimitEntry",
			"inactiveCurrentUsageLimitEntry",
			"usageLimitEntry",
		):
			limit_entry = entry.get(limit_key)
			if isinstance(limit_entry, dict):
				quota = limit_entry.get("usageQuotaMins")
				if quota is not None:
					try:
						today_limit = int(quota)
					except (ValueError, TypeError):
						pass
					break

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
