"""CASA R120 supply-air temperature control (not a room thermostat)."""
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy control platforms are disabled in the read-only release."""
    return

# underlag 

class CasaSupplyAirClimate(ClimateEntity):
    """Show T4 as actual temperature and 0x4D index 00 as setpoint.

    HEAT = temperature regulation permitted; actual reheater activity is
    reported independently by the existing CASA reheat status flag.
    """

    _attr_should_poll = False
    _attr_name = 'CASA Supply Air Climate'
    _attr_icon = 'mdi:hvac'
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 13
    _attr_max_temp = 20
    _attr_target_temperature_step = 1
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_supply_air_climate'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return (self.hub.connected
                and self.hub.supply_air_temperature_setpoint is not None
                and self.hub.temperature_setting_enabled is not None
                and self.hub.values.get('supply_temp_heated') is not None)

    @property
    def current_temperature(self):
        return self.hub.values.get('supply_temp_heated')

    @property
    def target_temperature(self):
        return self.hub.supply_air_temperature_setpoint

    @property
    def hvac_mode(self):
        enabled = self.hub.temperature_setting_enabled
        if enabled is None:
            return None
        return HVACMode.HEAT if enabled else HVACMode.OFF

    @property
    def hvac_action(self):
        # Reuse the same hub status as binary_sensor.casa_reheat.
        # Report actual reheating independently of the temperature permission.
        if self.hub.values.get('reheat') is True:
            return HVACAction.HEATING
        if self.hub.temperature_setting_enabled is False:
            return HVACAction.OFF
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        return {
            'current_temperature_source': 'T4 · supply air after heating',
            'target_temperature_source': '0x4D index 00',
            'hvac_mode_meaning': 'HEAT means temperature regulation permitted',
            'heating_element_active': self.hub.values.get('reheat'),
        }

    async def async_set_temperature(self, **kwargs):
        target = kwargs.get('temperature')
        if target is None:
            raise ValueError('Missing CASA supply air temperature target')
        await self.hub.set_supply_air_temperature_setpoint(target)

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in (HVACMode.HEAT, HVACMode.OFF):
            raise ValueError(f'Unsupported CASA HVAC mode: {hvac_mode}')
        await self.hub.set_temperature_setting(hvac_mode == HVACMode.HEAT)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

