"""CASA summer cooling temperature setting, confirmed via 0x3D status."""
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN, SERVICE_FAN_PROFILES


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return


class CasaSummerCoolingTemperature(NumberEntity):
    _attr_should_poll = False
    _attr_name = 'CASA Summer Cooling Temperature'
    _attr_native_min_value = 13
    _attr_native_max_value = 20
    _attr_native_step = 1
    _attr_native_unit_of_measurement = '°C'
    _attr_icon = 'mdi:thermometer'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_summer_cooling_temperature'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.cooling_settings is not None

    @property
    def native_value(self):
        if not self.available:
            return None
        return self.hub.cooling_settings[1]

    async def async_set_native_value(self, value):
        await self.hub.set_cooling_setting(temperature=value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaSupplyAirTemperatureSetpoint(NumberEntity):
    """R120 Premium temperature menu setpoint: 0x4D read / 0x4C write."""
    _attr_should_poll = False
    _attr_name = 'CASA Supply Air Temperature Setpoint'
    _attr_native_min_value = 13
    _attr_native_max_value = 20
    _attr_native_step = 1
    _attr_native_unit_of_measurement = '°C'
    _attr_icon = 'mdi:thermometer-lines'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_supply_air_temperature_setpoint'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.temperature_setting_data is not None

    @property
    def native_value(self):
        return self.hub.supply_air_temperature_setpoint if self.available else None

    async def async_set_native_value(self, value):
        await self.hub.set_supply_air_temperature_setpoint(value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaFanSpeedNumber(NumberEntity):
    _attr_should_poll = False
    _attr_native_min_value = 20
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = '%'
    _attr_icon = 'mdi:fan'

    def __init__(self, hub, key, level):
        self.hub, self.key, self.level = hub, key, level
        self._attr_name = f'CASA Service {"Supply" if key == "supply_fan" else "Extract"} Fan Level {level}'
        self._attr_unique_id = f'casa_premium_{hub.host}_service_{key}_{level}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.service_value(self.key) is not None

    @property
    def native_value(self):
        data = self.hub.service_value(self.key)
        return data[self.level - 1] if data else None

    async def async_set_native_value(self, value):
        await self.hub.set_fan_percentage(self.key, self.level, value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaFanProfileNumber(NumberEntity):
    _attr_should_poll = False
    _attr_native_min_value = 1
    _attr_native_max_value = 5
    _attr_native_step = 1
    _attr_icon = 'mdi:fan-auto'

    def __init__(self, hub, index):
        self.hub, self.index = hub, index
        self._attr_name = f'CASA Service Fan Profile {SERVICE_FAN_PROFILES[index]}'
        self._attr_unique_id = f'casa_premium_{hub.host}_service_profile_{index}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.service_value('fan_profiles') is not None

    @property
    def native_value(self):
        data = self.hub.service_value('fan_profiles')
        return data[self.index] if data else None

    async def async_set_native_value(self, value):
        await self.hub.set_fan_profile(self.index, value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


# (key, parameter, name, byte offset, min, max, increment, unit)
FUNCTION_NUMBERS = (
    ('service_interval','months','Service Reminder Interval',0,1,24,1,'months'),
    ('summer_night_cooling','temperature_difference','Summer Night Cooling Temperature Difference',3,0,15,1,'°C'),
    ('summer_night_cooling','temperature_limit','Summer Night Cooling Temperature Limit',2,5,25,1,'°C'),
    ('heating','temperature_limit','Heating Temperature Limit',1,10,70,1,'°C'),
    ('heating','p','Heating Supply Controller P',3,0,20,0.01,None),
    ('heating','i','Heating Supply Controller I',5,0,20,0.01,None),
    ('heating','d','Heating Supply Controller D',7,0,20,0.01,None),
    ('filter_monitor','delay','Filter Monitor Delay',1,0,240,1,'min'),
    ('sa_limit','minimum_supply_temperature','SA Limit Minimum Supply Temperature',0,5,25,1,'°C'),
    ('sa_limit','setpoint_difference','SA Limit Setpoint Difference',1,0,15,1,'°C'),
    ('electric_air_heater_temperature','temperature_setpoint','Electric Air Heater Temperature Setpoint',4,5,35,1,'°C'),
)

class CasaFunctionNumber(NumberEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:tune-vertical'

    def __init__(self, hub, key, parameter, name, offset, minimum, maximum, step, unit):
        self.hub, self.key, self.parameter, self.offset = hub, key, parameter, offset
        self._attr_name = f'CASA Functions {name}'
        self._attr_unique_id = f'casa_premium_{hub.host}_functions_{key}_{parameter}'
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        if unit:
            self._attr_native_unit_of_measurement = unit
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.service_value(self.key) is not None

    @property
    def native_value(self):
        data = self.hub.service_value(self.key)
        if data is None:
            return None
        if self.key == 'heating' and self.parameter in ('p','i','d'):
            return int.from_bytes(data[self.offset:self.offset+2], 'big') / 100
        return data[self.offset]

    async def async_set_native_value(self, value):
        await self.hub.set_function_number(self.key, self.parameter, value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaWeekTemperatureNumber(NumberEntity):
    _attr_should_poll = False
    _attr_native_min_value = 13
    _attr_native_max_value = 20
    _attr_native_step = 1
    _attr_native_unit_of_measurement = '°C'
    _attr_icon = 'mdi:thermometer'

    def __init__(self, hub, slot):
        self.hub, self.slot = hub, slot
        self._attr_name = f'CASA Week {slot+1} Temperature'
        self._attr_unique_id = f'casa_premium_{hub.host}_week_{slot+1}_temp'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.week_value(self.slot) is not None

    @property
    def native_value(self):
        data = self.hub.week_value(self.slot)
        return data[5] if data is not None else None

    async def async_set_native_value(self, value):
        await self.hub.set_week_temperature(self.slot, value)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

