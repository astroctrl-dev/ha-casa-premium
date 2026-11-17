"""CASA Fireplace switch, with physical unit as the source of truth."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from . import DOMAIN


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return


class CasaFireplaceSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_name = 'CASA Peisfunksjon'
    _attr_icon = 'mdi:fireplace'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_fireplace_switch'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def is_on(self):
        return self.hub.fireplace_active

    @property
    def available(self):
        return self.hub.connected and self.hub.fireplace_active is not None

    async def async_turn_on(self, **kwargs):
        try:
            await self.hub.set_fireplace(True)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def async_turn_off(self, **kwargs):
        try:
            await self.hub.set_fireplace(False)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaTemperatureMenuSwitch(SwitchEntity):
    """Read/write CASA temperature menu setting; only actual 0x4D state is shown."""
    _attr_should_poll = False
    _attr_name = 'CASA Temperature Setting'
    _attr_icon = 'mdi:thermometer-cog'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_temperature_setting_switch'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.temperature_setting_enabled is not None

    @property
    def is_on(self):
        return self.hub.temperature_setting_enabled

    @property
    def extra_state_attributes(self):
        return {'source': '0x4D', 'write_command': '0x4C',
                'parameter_selector': '0x20',
                'description': 'Temperature setting availability in panel menu'}

    async def async_turn_on(self, **kwargs):
        try:
            await self.hub.set_temperature_setting(True)
        except (ValueError, ConnectionError, TimeoutError) as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def async_turn_off(self, **kwargs):
        try:
            await self.hub.set_temperature_setting(False)
        except (ValueError, ConnectionError, TimeoutError) as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaWeeklyScheduleMenuSwitch(SwitchEntity):
    """Weekly schedule enable/disable, actual 0x37 status is authoritative."""
    _attr_should_poll = False
    _attr_name = 'CASA Service Weekly Schedule'
    _attr_icon = 'mdi:calendar-clock'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_service_weekly_schedule'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        data = self.hub.service_value('weekly_schedule')
        return self.hub.connected and data is not None and data[3] in (0, 1, 2)

    @property
    def is_on(self):
        data = self.hub.service_value('weekly_schedule')
        return data[3] == 2 if self.available else None

    async def async_turn_on(self, **kwargs):
        await self.hub.set_weekly_schedule(True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_weekly_schedule(False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


FUNCTION_SWITCHES = (
    ('service_reminder', 'Service Reminder', 'mdi:calendar-check'),
    ('summer_night_cooling', 'Summer Night Cooling', 'mdi:weather-night'),
    ('heating', 'Heating', 'mdi:radiator'),
    ('filter_monitor', 'Filter Monitor', 'mdi:air-filter'),
    ('fireplace_function', 'Fireplace Function Configuration', 'mdi:fireplace'),
    ('boost_special', 'Boost Special Configuration', 'mdi:fan-plus'),
    ('electric_air_heater', 'Electric Air Heater', 'mdi:radiator'),
)


class CasaWeeklyScheduleSwitch(SwitchEntity):
    """Main menu: actual native Week Schedule master enable (0x6E/0x6F)."""
    _attr_should_poll = False
    _attr_name = 'CASA Week Schedule Enabled'
    _attr_icon = 'mdi:calendar-clock'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_week_schedule_enabled'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.week_enabled is not None

    @property
    def is_on(self):
        return self.hub.week_enabled

    async def async_turn_on(self, **kwargs):
        await self.hub.set_week_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_week_enabled(False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaWeekDaySwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:calendar-check'
    DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

    def __init__(self, hub, slot, weekday):
        self.hub, self.slot, self.weekday = hub, slot, weekday
        self._attr_name = f'CASA Week {slot+1} {self.DAYS[weekday]}'
        self._attr_unique_id = f'casa_premium_{hub.host}_week_{slot+1}_day_{weekday}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.week_value(self.slot) is not None

    @property
    def is_on(self):
        data = self.hub.week_value(self.slot)
        return bool(data[0] & (1 << self.weekday)) if data is not None else None

    async def async_turn_on(self, **kwargs):
        await self.hub.set_week_day(self.slot, self.weekday, True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_week_day(self.slot, self.weekday, False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


FUNCTION_SWITCHES = (
    ('service_reminder', 'Service Reminder', 'mdi:calendar-check'),
    ('summer_night_cooling', 'Summer Night Cooling', 'mdi:weather-night'),
    ('heating', 'Heating', 'mdi:radiator'),
    ('filter_monitor', 'Filter Monitor', 'mdi:air-filter'),
    ('fireplace_function', 'Fireplace Function Configuration', 'mdi:fireplace'),
    ('boost_special', 'Boost Special Configuration', 'mdi:fan-plus'),
    ('electric_air_heater', 'Electric Air Heater', 'mdi:radiator'),
)

class CasaFunctionSwitch(SwitchEntity):
    _attr_should_poll = False

    def __init__(self, hub, key, name, icon):
        self.hub, self.key = hub, key
        self._attr_name = f'CASA Functions {name}'
        self._attr_icon = icon
        self._attr_unique_id = f'casa_premium_{hub.host}_functions_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def _index(self):
        return {'service_reminder':1, 'summer_night_cooling':0, 'heating':0,
                'filter_monitor':0, 'fireplace_function':3, 'boost_special':1,
                'electric_air_heater':4}[self.key]

    @property
    def available(self):
        data = self.hub.service_value(self.key)
        return data is not None and data[self._index] in (1, 2)

    @property
    def is_on(self):
        data = self.hub.service_value(self.key)
        return data[self._index] == 2 if self.available else None

    async def async_turn_on(self, **kwargs):
        await self.hub.set_function_enabled(self.key, True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_function_enabled(self.key, False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaAutoClockSyncSwitch(SwitchEntity, RestoreEntity):
    """Enable/disable only automatic clock correction (startup recovery + 04:15)."""

    _attr_should_poll = False
    _attr_name = 'CASA Auto Clock Sync'
    _attr_icon = 'mdi:clock-sync-outline'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_auto_clock_sync'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def is_on(self):
        return self.hub.auto_clock_sync_enabled

    @property
    def extra_state_attributes(self):
        return {'clock_sync_control_version': 2}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        # Old builds exposed this switch but did not obey its state.
        # Do not restore a potentially unsafe old ON value on migration.
        if (previous is not None and previous.state in ('on', 'off')
                and previous.attributes.get('clock_sync_control_version') == 2):
            self.hub.auto_clock_sync_enabled = previous.state == 'on'
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self.hub.auto_clock_sync_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self.hub.auto_clock_sync_enabled = False
        self.async_write_ha_state()

