"""Authentication helpers for Google Family Link.

Two authenticators are provided:

* :class:`PlaywrightAuthenticator` – fully automated browser login via
  Playwright.  Only available when the ``playwright`` package can be
  imported (x86-64, manylinux aarch64).  Use :func:`is_playwright_available`
  to check before instantiating.

* :class:`BrowserAuthenticator` – manual cookie-based fallback that works on
  every platform, including musl/Alpine aarch64 where Playwright wheels are
  not available.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
	BROWSER_NAVIGATION_TIMEOUT,
	BROWSER_TIMEOUT,
	FAMILYLINK_BASE_URL,
	LOGGER_NAME,
)
from ..exceptions import AuthenticationError, BrowserError, TimeoutError

_LOGGER = logging.getLogger(LOGGER_NAME)

# ---------------------------------------------------------------------------
# Optional playwright import
# ---------------------------------------------------------------------------
try:
	from playwright.async_api import async_playwright  # type: ignore[import]
	_PLAYWRIGHT_AVAILABLE = True
except ImportError:
	_PLAYWRIGHT_AVAILABLE = False


def is_playwright_available() -> bool:
	"""Return True if the playwright package is importable on this platform."""
	return _PLAYWRIGHT_AVAILABLE


# ---------------------------------------------------------------------------
# Playwright-based authenticator (preferred, requires playwright installed)
# ---------------------------------------------------------------------------

class PlaywrightAuthenticator:
	"""Handle automated browser-based authentication for Google Family Link.

	Opens a visible Chromium window so the user can complete the Google login
	flow interactively.  Cookies are extracted automatically once the Family
	Link dashboard is detected.

	Only instantiate this class after confirming :func:`is_playwright_available`
	returns ``True``.
	"""

	def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
		"""Initialize the browser authenticator."""
		self.hass = hass
		self.config = config
		self._browser: Any = None
		self._page: Any = None

	async def async_authenticate(self) -> dict[str, Any]:
		"""Open a browser, wait for login, return session cookies."""
		_LOGGER.debug("Starting Playwright browser authentication")

		try:
			async with async_playwright() as playwright:
				self._browser = await playwright.chromium.launch(
					headless=False,
					args=[
						"--no-sandbox",
						"--disable-blink-features=AutomationControlled",
						"--disable-extensions",
					],
				)
				self._page = await self._browser.new_page()

				await self._page.set_extra_http_headers({
					"User-Agent": (
						"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
						"AppleWebKit/537.36 (KHTML, like Gecko) "
						"Chrome/120.0.0.0 Safari/537.36"
					)
				})

				await self._page.goto(
					FAMILYLINK_BASE_URL,
					timeout=BROWSER_NAVIGATION_TIMEOUT,
				)

				return await self._wait_for_authentication()

		except (AuthenticationError, TimeoutError):
			raise
		except Exception as err:
			_LOGGER.error("Browser authentication failed: %s", err)
			raise BrowserError(f"Browser authentication failed: {err}") from err
		finally:
			await self._cleanup()

	async def _wait_for_authentication(self) -> dict[str, Any]:
		"""Wait for the Family Link dashboard to appear and extract cookies."""
		_LOGGER.info("Waiting for user to complete Google login in browser…")

		try:
			await self._page.wait_for_selector(
				'[data-testid="family-dashboard"]',
				timeout=BROWSER_TIMEOUT,
			)
		except asyncio.TimeoutError as err:
			_LOGGER.error("Authentication timed out")
			raise TimeoutError(
				"Authentication timed out – the login was not completed in time"
			) from err

		cookies = await self._page.context.cookies()
		relevant = [
			c for c in cookies
			if _is_google_domain(c.get("domain", ""))
		]

		if not relevant:
			raise AuthenticationError("No valid Google cookies found after login")

		_LOGGER.info("Browser authentication completed successfully")
		return {"cookies": relevant, "authenticated": True}

	async def _cleanup(self) -> None:
		"""Close browser resources."""
		try:
			if self._page:
				await self._page.close()
			if self._browser:
				await self._browser.close()
		except Exception as err:  # pylint: disable=broad-except
			_LOGGER.warning("Error during browser cleanup: %s", err)
		finally:
			self._page = None
			self._browser = None


# ---------------------------------------------------------------------------
# Cookie-based fallback authenticator (works on every platform)
# ---------------------------------------------------------------------------

class BrowserAuthenticator:
	"""Manual cookie-based authentication for Google Family Link.

	Used automatically on platforms where Playwright is not available
	(e.g. musl/Alpine aarch64).  The user logs in via their own browser and
	pastes their Google session cookies into the HA config flow.
	"""

	def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
		"""Initialize the cookie authenticator."""
		self.hass = hass
		self.config = config

	async def async_authenticate(self) -> dict[str, Any]:
		"""Parse and validate cookies supplied by the user."""
		_LOGGER.debug("Starting cookie-based authentication")

		papisid = (self.config.get("papisid") or "").strip()
		raw_cookies = (self.config.get("cookies_json") or "").strip()

		if papisid:
			cookie_list = [_build_papisid_cookie(papisid)]
		elif raw_cookies:
			try:
				cookie_list = _parse_cookies(raw_cookies)
			except (ValueError, TypeError) as err:
				_LOGGER.error("Failed to parse cookies: %s", err)
				raise BrowserError(f"Invalid cookie data: {err}") from err
		else:
			raise AuthenticationError(
				"Either papisid or cookies_json must be provided for authentication"
			)

		relevant = [c for c in cookie_list if _is_google_domain(c.get("domain", ""))]

		if not relevant:
			raise AuthenticationError(
				"No valid Google authentication cookies found. "
				f"Please log in to {FAMILYLINK_BASE_URL} in your browser, "
				"copy your cookies and paste them as JSON."
			)

		_LOGGER.info("Cookie authentication validated successfully")
		return {"cookies": relevant, "authenticated": True}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_google_domain(domain: str) -> bool:
	"""Return True if *domain* is google.com or a subdomain of google.com."""
	domain = domain.lstrip(".")
	return domain == "google.com" or domain.endswith(".google.com")


def _build_papisid_cookie(value: str) -> dict[str, Any]:
	"""Build a cookie dict for the ``__Secure-1PAPISID`` cookie."""
	return {
		"name": "__Secure-1PAPISID",
		"value": value,
		"domain": ".google.com",
		"path": "/",
		"secure": True,
		"httpOnly": False,
		"sameSite": "None",
	}


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
		parsed = json.loads(raw)
		if not isinstance(parsed, list):
			raise ValueError("Expected a JSON array of cookie objects")
		for item in parsed:
			if not isinstance(item, dict):
				raise ValueError("Each cookie must be a JSON object")
		return parsed

	# "name=value; name2=value2" header format
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