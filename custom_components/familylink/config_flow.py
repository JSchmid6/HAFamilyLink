"""Config flow for Google Family Link integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
	CONF_TIMEOUT,
	CONF_UPDATE_INTERVAL,
	DEFAULT_TIMEOUT,
	DEFAULT_UPDATE_INTERVAL,
	DOMAIN,
	FAMILYLINK_BASE_URL,
	INTEGRATION_NAME,
	LOGGER_NAME,
)
from .exceptions import AuthenticationError, BrowserError

_LOGGER = logging.getLogger(LOGGER_NAME)

STEP_USER_DATA_SCHEMA = vol.Schema(
	{
		vol.Required(CONF_NAME, default=INTEGRATION_NAME): str,
		vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
			vol.Coerce(int), vol.Range(min=30, max=3600)
		),
		vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
			vol.Coerce(int), vol.Range(min=10, max=120)
		),
	}
)

STEP_COOKIES_DATA_SCHEMA = vol.Schema(
	{
		vol.Required("cookies_json"): str,
	}
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	"""Handle a config flow for Google Family Link.

	Authentication strategy is selected automatically:

	* **Playwright available** (x86-64, manylinux ARM): a Chromium window
	  opens so the user can complete the Google login interactively.  No
	  manual cookie copying required.

	* **Playwright not available** (musl/Alpine aarch64 and similar): the
	  user is asked to paste their Google session cookies from their own
	  browser's DevTools (Application → Cookies).
	"""

	VERSION = 1

	def __init__(self) -> None:
		"""Initialize the config flow."""
		self._user_input: dict[str, Any] = {}

	# ------------------------------------------------------------------
	# Step 1 – basic settings
	# ------------------------------------------------------------------

	async def async_step_user(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Collect general settings, then route to the appropriate auth step."""
		if user_input is not None:
			self._user_input = user_input

			from .auth.browser import is_playwright_available
			if is_playwright_available():
				return await self.async_step_browser_auth()
			return await self.async_step_cookies()

		return self.async_show_form(
			step_id="user",
			data_schema=STEP_USER_DATA_SCHEMA,
		)

	# ------------------------------------------------------------------
	# Step 2a – automated browser auth (Playwright path)
	# ------------------------------------------------------------------

	async def async_step_browser_auth(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Run Playwright browser authentication.

		This step has no form – it opens a browser window automatically.
		On failure it falls back to the manual cookie entry step.
		"""
		from .auth.browser import PlaywrightAuthenticator

		_LOGGER.debug("Attempting Playwright browser authentication")
		try:
			auth = PlaywrightAuthenticator(self.hass, self._user_input)
			session_data = await auth.async_authenticate()

			if not session_data or "cookies" not in session_data:
				raise AuthenticationError("No valid session data received")

			return self.async_create_entry(
				title=self._user_input[CONF_NAME],
				data={**self._user_input, "cookies": session_data["cookies"]},
			)

		except Exception:  # pylint: disable=broad-except
			_LOGGER.warning(
				"Playwright authentication failed; falling back to manual cookie entry",
				exc_info=True,
			)
			return await self.async_step_cookies()

	# ------------------------------------------------------------------
	# Step 2b – manual cookie entry (fallback path)
	# ------------------------------------------------------------------

	async def async_step_cookies(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Ask the user to paste their Google session cookies.

		This step is used automatically when Playwright is not available on
		the current platform (e.g. musl/Alpine aarch64).
		"""
		errors: dict[str, str] = {}

		if user_input is not None:
			combined = {**self._user_input, **user_input}
			try:
				info = await _validate_cookie_input(self.hass, combined)
				entry_data = {**combined, "cookies": info["cookies"]}
				return self.async_create_entry(title=info["title"], data=entry_data)
			except CannotConnect:
				errors["base"] = "cannot_connect"
			except InvalidAuth:
				errors["base"] = "invalid_auth"
			except Exception:  # pylint: disable=broad-except
				_LOGGER.exception("Unexpected exception during cookie validation")
				errors["base"] = "unknown"

		return self.async_show_form(
			step_id="cookies",
			data_schema=STEP_COOKIES_DATA_SCHEMA,
			errors=errors,
			description_placeholders={"familylink_url": FAMILYLINK_BASE_URL},
		)

	# ------------------------------------------------------------------
	# Options flow
	# ------------------------------------------------------------------

	@staticmethod
	@config_entries.callback
	def async_get_options_flow(
		config_entry: config_entries.ConfigEntry,
	) -> "OptionsFlowHandler":
		"""Return the options flow handler."""
		return OptionsFlowHandler(config_entry)

	# ------------------------------------------------------------------
	# Import step
	# ------------------------------------------------------------------

	async def async_step_import(self, import_info: dict[str, Any]) -> FlowResult:
		"""Handle import from configuration.yaml."""
		await self.async_set_unique_id(DOMAIN)
		self._abort_if_unique_id_configured()

		try:
			info = await _validate_cookie_input(self.hass, import_info)
			return self.async_create_entry(title=info["title"], data=import_info)
		except (CannotConnect, InvalidAuth):
			return self.async_abort(reason="invalid_config")

	# ------------------------------------------------------------------
	# Re-authentication step (called when session/token expires)
	# ------------------------------------------------------------------

	async def async_step_reauth(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Handle re-authentication when the session expires."""
		return await self.async_step_reauth_confirm()

	async def async_step_reauth_confirm(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Ask the user to re-enter cookies to renew an expired session."""
		errors: dict[str, str] = {}

		existing_entry = self.hass.config_entries.async_get_entry(
			self.context["entry_id"]
		)
		if existing_entry is None:
			return self.async_abort(reason="entry_not_found")

		if user_input is not None:
			combined = {**existing_entry.data, **user_input}
			try:
				info = await _validate_cookie_input(self.hass, combined)
				entry_data = {**combined, "cookies": info["cookies"]}
				self.hass.config_entries.async_update_entry(
					existing_entry,
					data=entry_data,
				)
				await self.hass.config_entries.async_reload(existing_entry.entry_id)
				return self.async_abort(reason="reauth_successful")
			except CannotConnect:
				errors["base"] = "cannot_connect"
			except InvalidAuth:
				errors["base"] = "invalid_auth"
			except Exception:  # pylint: disable=broad-except
				_LOGGER.exception("Unexpected exception during re-authentication")
				errors["base"] = "unknown"

		return self.async_show_form(
			step_id="reauth_confirm",
			data_schema=STEP_COOKIES_DATA_SCHEMA,
			errors=errors,
			description_placeholders={"familylink_url": FAMILYLINK_BASE_URL},
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _validate_cookie_input(
	hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
	"""Validate manually supplied cookies."""
	from .auth.browser import BrowserAuthenticator

	cookies_json = (data.get("cookies_json") or "").strip()
	if not cookies_json:
		raise InvalidAuth

	try:
		auth = BrowserAuthenticator(hass, data)
		session_data = await auth.async_authenticate()

		if not session_data or "cookies" not in session_data:
			raise AuthenticationError("No valid session data received")

		return {
			"title": data[CONF_NAME],
			"cookies": session_data["cookies"],
		}

	except BrowserError as err:
		_LOGGER.error("Cookie authentication failed: %s", err)
		raise CannotConnect from err
	except AuthenticationError as err:
		_LOGGER.error("Authentication failed: %s", err)
		raise InvalidAuth from err
	except Exception as err:
		_LOGGER.exception("Unexpected error during cookie validation")
		raise CannotConnect from err


class CannotConnect(HomeAssistantError):
	"""Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
	"""Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
	"""Handle options for Family Link (polling interval, request timeout)."""

	def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
		"""Initialize the options flow."""
		self.config_entry = config_entry

	async def async_step_init(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Manage integration options."""
		if user_input is not None:
			return self.async_create_entry(title="", data=user_input)

		schema = vol.Schema(
			{
				vol.Optional(
					CONF_UPDATE_INTERVAL,
					default=self.config_entry.options.get(
						CONF_UPDATE_INTERVAL,
						self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
					),
				): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
				vol.Optional(
					CONF_TIMEOUT,
					default=self.config_entry.options.get(
						CONF_TIMEOUT,
						self.config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
					),
				): vol.All(vol.Coerce(int), vol.Range(min=10, max=120)),
			}
		)
		return self.async_show_form(step_id="init", data_schema=schema)