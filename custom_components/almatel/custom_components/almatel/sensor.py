"""Sensor platform for Almatel Balance integration."""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_RUBLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MQTT_STATE_TOPIC,
    MQTT_ATTR_TOPIC,
    ATTR_DUE_DATE,
    ATTR_DAYS_LEFT,
    ATTR_MESSAGE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Almatel Balance sensor from a config entry."""
    
    sensors = [
        AlmatelBalanceSensor(config_entry),
        AlmatelDueDateSensor(config_entry),
        AlmatelDaysLeftSensor(config_entry),
    ]
    
    async_add_entities(sensors)


class AlmatelBaseSensor(SensorEntity):
    """Base class for Almatel sensors."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._config_entry = config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "almatel_device_01")},
            name="Almatel Личный Кабинет",
            manufacturer="Almatel",
            model="WebChecker v2",
        )


class AlmatelBalanceSensor(AlmatelBaseSensor):
    """Representation of Almatel Balance sensor."""

    _attr_name = "Баланс"
    _attr_native_unit_of_measurement = CURRENCY_RUBLE
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the balance sensor."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{DOMAIN}_balance"
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        
        @callback
        def state_message_received(msg):
            """Handle new MQTT state messages."""
            try:
                self._attr_native_value = float(msg.payload)
                self.async_write_ha_state()
                _LOGGER.debug("Balance updated: %s", msg.payload)
            except (ValueError, TypeError) as e:
                _LOGGER.error("Failed to parse balance: %s", e)

        @callback
        def attr_message_received(msg):
            """Handle new MQTT attribute messages."""
            try:
                attributes = json.loads(msg.payload)
                self._attr_extra_state_attributes = {
                    ATTR_DUE_DATE: attributes.get("due_date"),
                    ATTR_DAYS_LEFT: attributes.get("days_left"),
                    ATTR_MESSAGE: attributes.get("message"),
                }
                self.async_write_ha_state()
                _LOGGER.debug("Attributes updated: %s", attributes)
            except (json.JSONDecodeError, TypeError) as e:
                _LOGGER.error("Failed to parse attributes: %s", e)

        await mqtt.async_subscribe(
            self.hass, MQTT_STATE_TOPIC, state_message_received, qos=0
        )
        await mqtt.async_subscribe(
            self.hass, MQTT_ATTR_TOPIC, attr_message_received, qos=0
        )


class AlmatelDueDateSensor(AlmatelBaseSensor):
    """Representation of Almatel Due Date sensor."""

    _attr_name = "Срок оплаты"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the due date sensor."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{DOMAIN}_due_date"

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        
        @callback
        def attr_message_received(msg):
            """Handle new MQTT attribute messages."""
            try:
                attributes = json.loads(msg.payload)
                due_date = attributes.get("due_date")
                if due_date:
                    # Конвертируем DD.MM.YYYY в YYYY-MM-DD для HA
                    parts = due_date.split(".")
                    if len(parts) == 3:
                        self._attr_native_value = f"{parts[2]}-{parts[1]}-{parts[0]}"
                        self.async_write_ha_state()
                        _LOGGER.debug("Due date updated: %s", self._attr_native_value)
            except (json.JSONDecodeError, TypeError, IndexError) as e:
                _LOGGER.error("Failed to parse due date: %s", e)

        await mqtt.async_subscribe(
            self.hass, MQTT_ATTR_TOPIC, attr_message_received, qos=0
        )


class AlmatelDaysLeftSensor(AlmatelBaseSensor):
    """Representation of Almatel Days Left sensor."""

    _attr_name = "Дней до оплаты"
    _attr_native_unit_of_measurement = "дней"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-today"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the days left sensor."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{DOMAIN}_days_left"
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when added to hass."""
        
        @callback
        def attr_message_received(msg):
            """Handle new MQTT attribute messages."""
            try:
                attributes = json.loads(msg.payload)
                days_left = attributes.get("days_left")
                message = attributes.get("message")
                
                if days_left is not None:
                    self._attr_native_value = int(days_left)
                    
                if message:
                    self._attr_extra_state_attributes = {
                        ATTR_MESSAGE: message
                    }
                    
                self.async_write_ha_state()
                _LOGGER.debug("Days left updated: %s", days_left)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                _LOGGER.error("Failed to parse days left: %s", e)

        await mqtt.async_subscribe(
            self.hass, MQTT_ATTR_TOPIC, attr_message_received, qos=0
        )
