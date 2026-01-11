"""Config flow for Almatel Balance integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
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
    """Handle a config flow for Almatel Balance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Проверяем, не добавлена ли уже интеграция
            await self.async_set_unique_id("almatel_balance")
            self._abort_if_unique_id_configured()

            # Сохраняем конфигурацию
            return self.async_create_entry(
                title="Almatel Balance",
                data=user_input,
            )

        # Схема формы для ввода данных
        data_schema = vol.Schema(
            {
                vol.Required(CONF_ALMATEL_LOGIN): cv.string,
                vol.Required(CONF_ALMATEL_PASSWORD): cv.string,
                vol.Required(
                    CONF_MQTT_HOST, default=DEFAULT_MQTT_HOST
                ): cv.string,
                vol.Required(
                    CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT
                ): cv.port,
                vol.Required(CONF_MQTT_USER): cv.string,
                vol.Required(CONF_MQTT_PASSWORD): cv.string,
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AlmatelOptionsFlowHandler:
        """Get the options flow for this handler."""
        return AlmatelOptionsFlowHandler(config_entry)


class AlmatelOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Almatel options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            self.config_entry.data.get(
                                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                            ),
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
                }
            ),
        )
