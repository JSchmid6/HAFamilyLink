"""Session management for Google Family Link authentication."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
	LOGGER_NAME,
)
from ..exceptions import SessionExpiredError

_LOGGER = logging.getLogger(LOGGER_NAME)


class SessionManager:
	"""Manage authentication sessions using cookies stored in the config entry."""

	def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
		"""Initialize the session manager."""
		self.hass = hass
		self.config = config
		self._session_data: dict[str, Any] | None = None

	async def async_load_session(self) -> dict[str, Any] | None:
		"""Load session data from the config entry."""
		cookies = self.config.get("cookies")
		if not cookies:
			_LOGGER.debug("No cookies found in config entry")
			return None

		session_data: dict[str, Any] = {"cookies": cookies}

		self._session_data = session_data
		_LOGGER.debug("Successfully loaded session data from config entry")
		return session_data

	async def async_save_session(self, session_data: dict[str, Any]) -> None:
		"""Update in-memory session data (persistence is handled by HA config entries)."""
		self._session_data = session_data
		_LOGGER.debug("Session data updated in memory")

	async def async_clear_session(self) -> None:
		"""Clear in-memory session data."""
		self._session_data = None
		_LOGGER.debug("Session data cleared")

	def get_cookies(self) -> list[dict[str, Any]]:
		"""Get cookies from current session."""
		if not self._session_data:
			raise SessionExpiredError("No active session")

		return self._session_data.get("cookies", [])

	# Core Google authentication cookie names that are required for a valid
	# session.  If ANY of these cookies is present and has explicitly expired
	# the whole session is considered invalid.  Non-auth cookies (analytics,
	# tracking, …) are intentionally excluded from this check so that a
	# harmless stale cookie cannot invalidate an otherwise working session.
	_AUTH_COOKIE_NAMES: frozenset[str] = frozenset(
		{
			"SID",
			"HSID",
			"SSID",
			"APISID",
			"SAPISID",
			"__Secure-1PSID",
			"__Secure-3PSID",
			"__Secure-1PAPISID",
			"__Secure-3PAPISID",
		}
	)

	def is_authenticated(self) -> bool:
		"""Check if we have a valid session with cookies.

		A session is considered valid as long as cookies are present and
		none of the known Google authentication cookies have an expiry
		timestamp (``expires`` or ``expirationDate``) that lies in the past.
		Cookies that carry no explicit expiry are always treated as valid.
		"""
		if not self._session_data:
			return False
		cookies = self._session_data.get("cookies", [])
		if not cookies:
			return False

		now = dt_util.utcnow().timestamp()
		for cookie in cookies:
			name = cookie.get("name", "")
			if name not in self._AUTH_COOKIE_NAMES:
				# Only check expiry for the critical auth cookies.
				continue
			# Support both field names used by different browser extensions.
			expires = cookie.get("expires") or cookie.get("expirationDate")
			if expires and isinstance(expires, (int, float)) and expires > 0:
				if now > expires:
					_LOGGER.debug(
						"Auth cookie '%s' has expired (expires=%s, now=%s)",
						name,
						expires,
						now,
					)
					return False
		return True 