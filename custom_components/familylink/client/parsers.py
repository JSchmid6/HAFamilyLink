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

	Returns a dict with keys ``limited``, ``blocked``, and ``always_allowed``.
	"""
	limited: list[dict[str, Any]] = []
	blocked: list[str] = []
	always_allowed: list[str] = []

	for app in raw.get("apps", []):
		title = app.get("title", app.get("packageName", ""))
		settings = app.get("supervisionSetting", {})
		if settings.get("hidden", False):
			blocked.append(title)
		elif (limit := settings.get("usageLimit")):
			limited.append({"app": title, "limit_minutes": limit.get("dailyUsageLimitMins")})
		elif (
			settings.get("alwaysAllowedAppInfo", {}).get("alwaysAllowedState")
			== "alwaysAllowedStateEnabled"
		):
			always_allowed.append(title)

	return {"limited": limited, "blocked": blocked, "always_allowed": always_allowed}
