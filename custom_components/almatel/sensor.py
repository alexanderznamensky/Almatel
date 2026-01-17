"""Sensor platform for Almatel integration."""
from __future__ import annotations

import json
import logging
from typing import Any
from datetime import datetime, timezone

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MQTT_STATE_TOPIC, MQTT_ATTR_TOPIC

_LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    """Current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _decode_payload(payload: Any) -> str:
    """MQTT payload may be str or bytes depending on HA/mqtt stack."""
    if payload is None:
        return ""
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", errors="ignore")
    return str(payload)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([AlmatelAdSensor(config_entry)])


class AlmatelAdSensor(SensorEntity):
    """Single sensor: state=balance, attrs=due_date/days_left/message/last_update."""

    _attr_has_entity_name = False
    _attr_name = "Almatel Баланс"
    _attr_unique_id = f"{DOMAIN}_almatelad"

    _attr_native_unit_of_measurement = "RUB"
    _attr_icon = "mdi:cash"

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "almatel_device_01")},
            name="Almatel Личный Кабинет",
            manufacturer="Almatel",
            model="WebChecker v2",
        )

        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self._unsubs: list = []

    async def async_added_to_hass(self) -> None:
        @callback
        def on_state(msg) -> None:
            try:
                raw = _decode_payload(msg.payload)
                self._attr_native_value = float(raw)

                attrs = dict(self._attr_extra_state_attributes or {})
                attrs["last_update"] = _now_iso()
                self._attr_extra_state_attributes = attrs

                self.async_write_ha_state()
                _LOGGER.debug("Balance updated: %s", raw)

            except (ValueError, TypeError) as e:
                _LOGGER.error("Failed to parse balance from '%s': %s", msg.payload, e)

        @callback
        def on_attr(msg) -> None:
            raw = _decode_payload(msg.payload)
            try:
                data = json.loads(raw)

                due_date = data.get("due_date")
                days_left = data.get("days_left")
                message = data.get("message")

                attrs = dict(self._attr_extra_state_attributes or {})

                if due_date is not None:
                    attrs["due_date"] = str(due_date)

                if days_left is not None:
                    try:
                        attrs["days_left"] = int(days_left)
                    except (ValueError, TypeError):
                        attrs["days_left"] = days_left

                if message is not None:
                    attrs["message"] = str(message)

                attrs["last_update"] = _now_iso()
                self._attr_extra_state_attributes = attrs

                self.async_write_ha_state()
                _LOGGER.debug("Attributes updated: %s", attrs)

            except json.JSONDecodeError as e:
                _LOGGER.error("Bad JSON in MQTT_ATTR_TOPIC: '%s' (%s)", raw, e)

        unsub1 = await mqtt.async_subscribe(self.hass, MQTT_STATE_TOPIC, on_state, qos=0)
        unsub2 = await mqtt.async_subscribe(self.hass, MQTT_ATTR_TOPIC, on_attr, qos=0)

        self._unsubs.extend([unsub1, unsub2])

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()
