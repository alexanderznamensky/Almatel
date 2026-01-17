"""Config flow for Almatel integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_ALMATEL_LOGIN,
    CONF_ALMATEL_PASSWORD,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MQTT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_MQTT_HOST,
)

_LOGGER = logging.getLogger(__name__)


class AlmatelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Almatel."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            await self.async_set_unique_id("almatelad")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Almatel", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ALMATEL_LOGIN): cv.string,
                vol.Required(CONF_ALMATEL_PASSWORD): cv.string,
                vol.Required(CONF_MQTT_HOST, default=DEFAULT_MQTT_HOST): cv.string,
                vol.Required(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): cv.port,
                vol.Required(CONF_MQTT_USER, default=""): cv.string,
                vol.Required(CONF_MQTT_PASSWORD, default=""): cv.string,
                vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=1440)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return AlmatelOptionsFlowHandler(config_entry)


class AlmatelOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Almatel."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                return self.async_create_entry(title="", data=user_input)
            except Exception as e:
                _LOGGER.exception("❌ Failed to save options: %s", e)
                errors["base"] = "unknown"

        options = dict(self._config_entry.options or {})
        data = dict(self._config_entry.data or {})

        raw_interval = options.get(
            CONF_UPDATE_INTERVAL,
            data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        try:
            current_interval = int(raw_interval)
        except (TypeError, ValueError):
            current_interval = DEFAULT_UPDATE_INTERVAL

        current_interval = max(5, min(1440, current_interval))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_UPDATE_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=1440)
                    ),
                }
            ),
            errors=errors,
        )
