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

	def is_authenticated(self) -> bool:
		"""Check if we have a valid session with cookies.

		Cookies without an ``expires`` field (session-only cookies) or with
		``expires <= 0`` are treated as still valid; only cookies with a
		positive expiry timestamp that has passed are considered expired.
		"""
		if not self._session_data:
			return False
		cookies = self._session_data.get("cookies", [])
		if not cookies:
			return False
		# Check if any cookie has explicitly expired
		now = dt_util.utcnow().timestamp()
		for cookie in cookies:
			expires = cookie.get("expires")
			if expires and isinstance(expires, (int, float)) and expires > 0:
				if now > expires:
					_LOGGER.debug("Cookie '%s' has expired", cookie.get("name"))
					return False
		return True 