"""The Almatel Balance integration."""
from __future__ import annotations

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    DOMAIN,
    CONF_ALMATEL_LOGIN,
    CONF_ALMATEL_PASSWORD,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    CONF_UPDATE_INTERVAL,
    SERVICE_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Almatel Balance from a config entry."""
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    await async_save_config_for_appdaemon(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE):
        async def handle_update_balance(call: ServiceCall) -> None:
            """Handle the service call to update balance."""
            await async_trigger_button_press(hass)

        hass.services.async_register(DOMAIN, SERVICE_UPDATE, handle_update_balance)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await async_save_config_for_appdaemon(hass, entry)
    _LOGGER.info("Almatel configuration updated")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE)

    return unload_ok


async def async_save_config_for_appdaemon(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Save configuration to a file that AppDaemon can read."""
    config_path = hass.config.path("almatel_config.json")
    
    config_data = {
        "almatel": {
            "login": entry.data[CONF_ALMATEL_LOGIN],
            "password": entry.data[CONF_ALMATEL_PASSWORD],
        },
        "mqtt": {
            "host": entry.data[CONF_MQTT_HOST],
            "port": entry.data.get(CONF_MQTT_PORT, 1883),
            "user": entry.data[CONF_MQTT_USER],
            "password": entry.data[CONF_MQTT_PASSWORD],
        },
        "update_interval": entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, 60)
        ),
    }

    def write_config():
        """Write config file."""
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        _LOGGER.info("Almatel config saved to %s", config_path)

    await hass.async_add_executor_job(write_config)


async def async_trigger_button_press(hass: HomeAssistant) -> None:
    """Trigger AppDaemon update by pressing input_button."""
    button_entity_id = "input_button.manual_almatel_check"
    
    try:
        state = hass.states.get(button_entity_id)
        
        if state is None:
            _LOGGER.warning(
                "Button %s not found. Please create it in configuration.yaml",
                button_entity_id
            )
            return
        
        await hass.services.async_call(
            "input_button",
            "press",
            {"entity_id": button_entity_id},
            blocking=False,
        )
        _LOGGER.info("Button %s pressed successfully", button_entity_id)
        
    except Exception as e:
        _LOGGER.error("Failed to press button %s: %s", button_entity_id, e)
