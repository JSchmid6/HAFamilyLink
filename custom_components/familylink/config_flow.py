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
	CONF_COOKIE_FILE,
	CONF_TIMEOUT,
	CONF_UPDATE_INTERVAL,
	DEFAULT_COOKIE_FILE,
	DEFAULT_TIMEOUT,
	DEFAULT_UPDATE_INTERVAL,
	DOMAIN,
	FAMILYLINK_BASE_URL,
	INTEGRATION_NAME,
	LOGGER_NAME,
)
from .exceptions import AuthenticationError, BrowserError, FamilyLinkException

_LOGGER = logging.getLogger(LOGGER_NAME)

STEP_USER_DATA_SCHEMA = vol.Schema(
	{
		vol.Required(CONF_NAME, default=INTEGRATION_NAME): str,
		vol.Optional(CONF_COOKIE_FILE, default=DEFAULT_COOKIE_FILE): str,
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


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
	"""Validate the user-supplied cookies."""
	from .auth.browser import BrowserAuthenticator

	try:
		authenticator = BrowserAuthenticator(hass, data)
		session_data = await authenticator.async_authenticate()

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
		_LOGGER.exception("Unexpected error during validation")
		raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	"""Handle a config flow for Google Family Link."""

	VERSION = 1

	def __init__(self) -> None:
		"""Initialize the config flow."""
		self._user_input: dict[str, Any] = {}

	async def async_step_user(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Handle the initial step – basic settings."""
		errors: dict[str, str] = {}

		if user_input is not None:
			self._user_input = user_input
			# Proceed to the cookie entry step
			return await self.async_step_cookies()

		return self.async_show_form(
			step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
		)

	async def async_step_cookies(
		self, user_input: dict[str, Any] | None = None
	) -> FlowResult:
		"""Handle the cookie entry step.

		The user is instructed to log in to Family Link in their own browser,
		copy their cookies (e.g. via browser DevTools → Application → Cookies),
		and paste them here as a JSON array or as a ``name=value`` header string.
		This avoids the need for Playwright or any other browser-automation library
		that may not be available on all platforms (e.g. linux_aarch64).
		"""
		errors: dict[str, str] = {}

		if user_input is not None:
			combined = {**self._user_input, **user_input}
			try:
				info = await validate_input(self.hass, combined)
				return self.async_create_entry(title=info["title"], data=combined)

			except CannotConnect:
				errors["base"] = "cannot_connect"
			except InvalidAuth:
				errors["base"] = "invalid_auth"
			except Exception:  # pylint: disable=broad-except
				_LOGGER.exception("Unexpected exception")
				errors["base"] = "unknown"

		description_placeholders = {"familylink_url": FAMILYLINK_BASE_URL}

		return self.async_show_form(
			step_id="cookies",
			data_schema=STEP_COOKIES_DATA_SCHEMA,
			errors=errors,
			description_placeholders=description_placeholders,
		)

	async def async_step_import(self, import_info: dict[str, Any]) -> FlowResult:
		"""Handle import from configuration.yaml."""
		await self.async_set_unique_id(DOMAIN)
		self._abort_if_unique_id_configured()

		try:
			info = await validate_input(self.hass, import_info)
			return self.async_create_entry(title=info["title"], data=import_info)
		except (CannotConnect, InvalidAuth):
			return self.async_abort(reason="invalid_config")


class CannotConnect(HomeAssistantError):
	"""Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
	"""Error to indicate there is invalid auth.""" 