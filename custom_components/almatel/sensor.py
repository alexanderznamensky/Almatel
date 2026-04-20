from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlmatelDataUpdateCoordinator

_ATTR_CURRENCY = "RUB"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AlmatelDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            AlmatelBalanceSensor(coordinator, entry),
        ]
    )


class AlmatelBalanceSensor(CoordinatorEntity[AlmatelDataUpdateCoordinator], SensorEntity):
    _attr_icon = "mdi:cash"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = _ATTR_CURRENCY

    def __init__(self, coordinator: AlmatelDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_balance"
        self._attr_name = "Almatel Баланс"

    @property
    def native_value(self):
        return self.coordinator.data.get("balance")

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "last_update": data.get("last_update"),
            "due_date": data.get("due_date"),
            "days_left": data.get("days_left"),
            "message": data.get("message"),
            "contract_number": data.get("contract_number"),
            "period_start": data.get("period_start"),
            "period_end": data.get("period_end"),
            "paid_until": data.get("paid_until"),
            "ip_address": data.get("ip_address"),
            "tariff_price": data.get("tariff_price"),
            "static_ip_price": data.get("static_ip_price"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        contract_number = self.coordinator.data.get("contract_number") or self._entry.entry_id

        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Almatel Личный Кабинет",
            manufacturer="Almatel",
            model="Личный кабинет",
            serial_number=str(contract_number),
        )