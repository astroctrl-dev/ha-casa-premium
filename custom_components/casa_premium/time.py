"""CASA native week program times (HH:MM, supports overnight intervals)."""
from datetime import time
from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return


class CasaWeekTime(TimeEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:clock-outline'

    def __init__(self, hub, slot, start):
        self.hub, self.slot, self.start = hub, slot, start
        field = 'From' if start else 'To'
        self._attr_name = f'CASA Week {slot+1} {field}'
        self._attr_unique_id = f'casa_premium_{hub.host}_week_{slot+1}_{field.lower()}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.week_value(self.slot) is not None

    @property
    def native_value(self):
        data = self.hub.week_value(self.slot)
        if data is None:
            return None
        offset = 1 if self.start else 3
        return time(data[offset], data[offset + 1])

    async def async_set_value(self, value: time) -> None:
        await self.hub.set_week_time(self.slot, self.start, value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

