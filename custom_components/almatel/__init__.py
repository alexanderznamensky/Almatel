"""The Almatel Balance integration."""
from __future__ import annotations

import json
import logging

import paho.mqtt.publish as publish

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components import mqtt

from . import sensor

from .const import (
    DOMAIN,
    CONF_ALMATEL_LOGIN,
    CONF_ALMATEL_PASSWORD,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USER,
    CONF_MQTT_PASSWORD,
    CONF_UPDATE_INTERVAL,
    MQTT_COMMAND_TOPIC,
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

    async def handle_update_balance(call: ServiceCall) -> None:
        """Handle the service call to update balance."""
        await async_trigger_appdaemon_update(hass, entry)

    hass.services.async_register(DOMAIN, SERVICE_UPDATE, handle_update_balance)

    await async_trigger_appdaemon_update(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

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


async def async_trigger_appdaemon_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Send MQTT command to trigger AppDaemon update via HA MQTT connection."""
    try:
        await mqtt.async_publish(
            hass,
            MQTT_COMMAND_TOPIC,
            "update",
            qos=0,
            retain=False,
        )
        _LOGGER.info("MQTT command published to %s", MQTT_COMMAND_TOPIC)
    except Exception as e:
        _LOGGER.exception("Failed to publish MQTT command: %s", e)
