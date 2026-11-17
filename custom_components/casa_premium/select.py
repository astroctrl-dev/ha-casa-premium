"""CASA ventilation mode selector with translated options and summer cooling fan."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from . import DOMAIN, MODE_PAYLOADS, COOLING_FAN_OPTIONS, COOLING_FAN_LABELS, WEEK_MODE_LABELS, WEEK_MODE_VALUES


# Internal values must remain stable across languages.
MODE_LABELS = {
    "Away": "away",
    "Home": "home",
    "Boost 30": "boost_30",
    "Boost 60": "boost_60",
    "Boost 120": "boost_120",
    "Boost permanent": "boost_permanent",
    "Fireplace 10": "fireplace_10",
}

REVERSE_LABELS = {
    label: mode for mode, label in MODE_LABELS.items()
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return


class CasaModeSelect(SelectEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "ventilation_mode"
    _attr_icon = "mdi:hvac"
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, hub):
        self.hub = hub

        # Preserve existing unique_id.
        self._attr_unique_id = (
            f"casa_premium_{hub.host}_mode_select"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name="Swegon CASA Premium",
            manufacturer="Swegon",
        )

    @property
    def current_option(self):
        return MODE_LABELS.get(self.hub.actual_mode)

    @property
    def available(self):
        return self.hub.connected

    async def async_select_option(self, option):
        mode = REVERSE_LABELS.get(option)

        if mode is None:
            raise HomeAssistantError(
                f"Unknown ventilation mode: {option}"
            )

        if mode == "Fireplace 10":
            raise HomeAssistantError(
                "Fireplace mode is controlled by its own switch"
            )

        if self.hub.fireplace_active is None:
            raise HomeAssistantError(
                "Waiting for CASA fireplace status"
            )

        if self.hub.fireplace_active:
            raise HomeAssistantError(
                "Disable fireplace mode using the switch first"
            )

        await self.hub.set_mode(mode)

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.hub.subscribe(self.async_write_ha_state)
        )


class CasaSummerCoolingFanSelect(SelectEntity):
    """Saved summer cooling fan choice; does not switch operating mode."""
    _attr_should_poll = False
    _attr_name = 'CASA Summer Cooling Fan'
    _attr_options = list(COOLING_FAN_OPTIONS)
    _attr_icon = 'mdi:fan'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_summer_cooling_fan'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.cooling_settings is not None

    @property
    def current_option(self):
        if not self.available:
            return None
        return COOLING_FAN_LABELS.get(self.hub.cooling_settings[4])

    async def async_select_option(self, option):
        await self.hub.set_cooling_setting(fan=option)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaHeatingControlSelect(SelectEntity):
    """Service -> Functions -> Heating -> Control (Supply / Extract)."""
    _attr_should_poll = False
    _attr_name = 'CASA Functions Heating Control'
    _attr_icon = 'mdi:hvac'
    _attr_options = ['Supply', 'Extract']

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_functions_heating_control'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        data = self.hub.service_value('heating')
        return data is not None and data[2] in (0, 1)

    @property
    def current_option(self):
        data = self.hub.service_value('heating')
        return ('Supply' if data[2] == 0 else 'Extract') if self.available else None

    async def async_select_option(self, option):
        await self.hub.set_heating_control(option)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaWeekModeSelect(SelectEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:fan'
    _attr_options = list(WEEK_MODE_LABELS)

    def __init__(self, hub, slot):
        self.hub, self.slot = hub, slot
        self._attr_name = f'CASA Week {slot+1} Ventilation'
        self._attr_unique_id = f'casa_premium_{hub.host}_week_{slot+1}_mode'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        data = self.hub.week_value(self.slot)
        return data is not None and data[6] in WEEK_MODE_VALUES

    @property
    def current_option(self):
        data = self.hub.week_value(self.slot)
        return WEEK_MODE_VALUES.get(data[6]) if data is not None else None

    async def async_select_option(self, option):
        await self.hub.set_week_mode(self.slot, option)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

