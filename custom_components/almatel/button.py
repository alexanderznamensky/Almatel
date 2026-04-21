from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlmatelDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AlmatelDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            AlmatelRefreshButton(coordinator, entry),
        ]
    )


class AlmatelRefreshButton(CoordinatorEntity[AlmatelDataUpdateCoordinator], ButtonEntity):
    _attr_icon = "mdi:refresh"
    _attr_name = "Обновить данные"

    def __init__(self, coordinator: AlmatelDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh"

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

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()