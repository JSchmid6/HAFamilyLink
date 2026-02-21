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
	# session.  Kept for reference / future use.
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

		Intentionally optimistic: we only verify that the SAPISID (or its
		Secure variant) cookie is present and has not yet expired.  We do NOT
		reject the session if other short-lived auxiliary cookies have expired
		– those are refreshed transparently by Google and do not affect the
		ability to make API calls.

		Real authentication failures (HTTP 401 from the API) are handled in
		the coordinator via ``_async_refresh_auth()``, which triggers the HA
		re-authentication flow.  Over-eager expiry checks here caused false
		"session expired" notifications on every HA restart.
		"""
		if not self._session_data:
			return False
		cookies = self._session_data.get("cookies", [])
		if not cookies:
			return False

		now = dt_util.utcnow().timestamp()
		# Only check the primary SAPISID cookies – these are what we actually
		# use to build the SAPISIDHASH Authorization header.
		_SAPISID_NAMES = {"SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID", "APISID"}
		sapisid_found = False
		for cookie in cookies:
			name = cookie.get("name", "")
			if name not in _SAPISID_NAMES:
				continue
			sapisid_found = True
			expires = cookie.get("expires") or cookie.get("expirationDate")
			if expires and isinstance(expires, (int, float)) and expires > 0:
				if now > expires:
					_LOGGER.debug(
						"SAPISID cookie '%s' has expired (expires=%s, now=%s)",
						name, expires, now,
					)
					return False
			# Found a non-expired SAPISID – session is valid.
			return True

		# If no SAPISID cookie was found at all, still allow the attempt –
		# the API call will fail with 401 if the session is truly gone.
		if not sapisid_found:
			_LOGGER.debug("No SAPISID cookie found; attempting API call anyway")
		return True 