"""Cookie-based authentication for Google Family Link."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
	FAMILYLINK_BASE_URL,
	LOGGER_NAME,
)
from ..exceptions import AuthenticationError, BrowserError

_LOGGER = logging.getLogger(LOGGER_NAME)


class BrowserAuthenticator:
	"""Handle cookie-based authentication for Google Family Link.

	Instead of browser automation (which is not available on all platforms,
	e.g. linux_aarch64), users supply their Google session cookies obtained
	from a browser of their choice.
	"""

	def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
		"""Initialize the authenticator."""
		self.hass = hass
		self.config = config

	_GOOGLE_DOMAINS = frozenset(
		{".google.com", "google.com", "accounts.google.com", "families.google.com"}
	)

	async def async_authenticate(self) -> dict[str, Any]:
		"""Parse and validate cookies supplied by the user."""
		_LOGGER.debug("Starting cookie-based authentication")

		raw_cookies = self.config.get("cookies_json", "")

		try:
			cookie_list = self._parse_cookies(raw_cookies)
		except (ValueError, TypeError) as err:
			_LOGGER.error("Failed to parse cookies: %s", err)
			raise BrowserError(f"Invalid cookie data: {err}") from err

		relevant_cookies = [
			cookie for cookie in cookie_list
			if self._is_google_domain(cookie.get("domain", ""))
		]

		if not relevant_cookies:
			raise AuthenticationError(
				"No valid Google authentication cookies found. "
				f"Please log in to {FAMILYLINK_BASE_URL} in your browser, "
				"copy your cookies and paste them as JSON."
			)

		_LOGGER.info("Cookie authentication validated successfully")

		return {
			"cookies": relevant_cookies,
			"authenticated": True,
		}

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	@classmethod
	def _is_google_domain(cls, domain: str) -> bool:
		"""Return True if *domain* is an exact match or subdomain of google.com."""
		domain = domain.lstrip(".")
		return domain == "google.com" or domain.endswith(".google.com")

	@staticmethod
	def _parse_cookies(raw: str) -> list[dict[str, Any]]:
		"""Parse a cookie string into a list of cookie dicts.

		Accepts two formats:

		- **JSON array** (recommended – preserves exact domain info)::

			[{"name": "SID", "value": "...", "domain": ".google.com"}, ...]

		- **Cookie header string** (convenience – domain defaults to ``.google.com``)::

			SID=value; HSID=value2

		  Because domain information is lost in the header format, all cookies
		  are assigned the ``.google.com`` root domain.  Use the JSON format when
		  you need precise per-cookie domain scoping.
		"""
		raw = (raw or "").strip()
		if not raw:
			raise ValueError("Cookie data is empty")

		if raw.startswith("["):
			# JSON array format
			parsed = json.loads(raw)
			if not isinstance(parsed, list):
				raise ValueError("Expected a JSON array of cookie objects")
			for item in parsed:
				if not isinstance(item, dict):
					raise ValueError("Each cookie must be a JSON object")
			return parsed

		# Simple "name=value; name2=value2" header format
		cookies: list[dict[str, Any]] = []
		for part in raw.split(";"):
			part = part.strip()
			if "=" in part:
				name, _, value = part.partition("=")
				cookies.append({
					"name": name.strip(),
					"value": value.strip(),
					"domain": ".google.com",
				})
		if not cookies:
			raise ValueError("Could not parse any cookies from the provided string")
		return cookies 