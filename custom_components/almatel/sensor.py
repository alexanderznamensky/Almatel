
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import SENSOR_TOPIC_TEMPLATE
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([MQTTSensor(hass, entry)], True)

class MQTTSensor(SensorEntity):
    def __init__(self, hass, entry):
        self._hass = hass
        self._entry = entry
        self._state = None
        self._attr_name = entry.data["name"]
        self._attr_unique_id = f"almatel_" + entry.data["sensor_id"]
        self._topic = SENSOR_TOPIC_TEMPLATE.format(sensor_id=entry.data["sensor_id"])

    async def async_added_to_hass(self):
        try:
            await self._hass.components.mqtt.async_subscribe(self._topic, self.mqtt_message_received)
        except Exception as e:
            _LOGGER.error(f"MQTT not available for sensor {self._attr_name}: {e}")

    async def mqtt_message_received(self, msg):
        self._state = msg.payload
        self.async_write_ha_state()

    @property
    def state(self):
        return self._state
