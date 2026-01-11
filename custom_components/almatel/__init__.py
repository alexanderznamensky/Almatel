"""The Almatel Balance integration."""
from __future__ import annotations

import json
import logging

import paho.mqtt.publish as publish

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

# Предварительная загрузка платформ для избежания блокирующего импорта
from . import sensor  # noqa: F401

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

    # Сохраняем настройки в файл для AppDaemon
    await async_save_config_for_appdaemon(hass, entry)

    # Настраиваем платформы
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Регистрируем сервис для ручного обновления
    async def handle_update_balance(call: ServiceCall) -> None:
        """Handle the service call to update balance."""
        await async_trigger_appdaemon_update(hass, entry)

    hass.services.async_register(DOMAIN, SERVICE_UPDATE, handle_update_balance)

    # Отправляем команду AppDaemon для первого запуска
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


async def async_trigger_appdaemon_update(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Send MQTT command to trigger AppDaemon update."""
    
    def send_mqtt_command():
        """Send MQTT command."""
        try:
            publish.single(
                topic=MQTT_COMMAND_TOPIC,
                payload="update",
                retain=False,
                hostname=entry.data[CONF_MQTT_HOST],
                port=entry.data.get(CONF_MQTT_PORT, 1883),
                auth={
                    "username": entry.data[CONF_MQTT_USER],
                    "password": entry.data[CONF_MQTT_PASSWORD]
                }
            )
            _LOGGER.info("MQTT command sent to AppDaemon")
        except Exception as e:
            _LOGGER.error("Failed to send MQTT command: %s", e)

    await hass.async_add_executor_job(send_mqtt_command)
