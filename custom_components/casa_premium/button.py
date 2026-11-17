"""CASA service enable flags: explicitly disable-only operations."""
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return


class CasaServiceDisableButton(ButtonEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:cancel'

    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_name = ('CASA Disable CO2 Control' if key == 'co2_control'
                           else 'CASA Disable External Control')
        self._attr_unique_id = f'casa_premium_{hub.host}_disable_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.service_value(self.key) is not None

    async def async_press(self):
        if self.key == 'co2_control':
            await self.hub.disable_co2_control()
        else:
            await self.hub.disable_external_control()


class CasaSyncClockNowButton(ButtonEntity):
    """Request one manual clock sync; does not enable automatic sync."""

    _attr_should_poll = False
    _attr_name = 'CASA Sync Clock Now'
    _attr_icon = 'mdi:clock-sync'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_sync_clock_now'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected

    async def async_press(self):
        # No force=True: only write when weekday/drift requires correction.
        # Executed in the background so a slow 0x55 cycle does not block the UI.
        _LOGGER.warning('CASA Sync Clock Now pressed; auto sync=%s',
                        self.hub.auto_clock_sync_enabled)
        self.hass.async_create_background_task(
            self.hub.sync_clock(automatic=False, use_recent_status=True),
            'CASA manual clock sync')

