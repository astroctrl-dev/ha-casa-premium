"""CASA status flags and alarms."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from time import monotonic
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN, SERVICE_CONFIG
from .entity import CasaEntity, configure_translation
from .readback import SERVICE_FLAGS, service_choice_value

FLAGS = ('heating','cooling','bypass','freeze_protection','preheat','chilling','preheater_overheat','reheat','fireplace','underpressure_compensation','external_boost','humidity_boost','co2_boost','defrosting','defrost_starter','tf_stop','external_boost_function','external_fireplace_function','filter_guard_status','ir_freeze_protection','emergency_stop','reheating_freezing_alarm','reheating_overheat_alarm','ir_sensor_failure','supply_fan_failure','extract_fan_failure','temperature_deviation_failure','efficiency_alarm','filter_guard_alarm','service_reminder','temperature_failure')


BINARY_NAMES = {
    'heating': 'Heating Active',
    'cooling': 'Cooling Active',
    'bypass': 'Heat Exchanger Bypass',
    'freeze_protection': 'Freeze Protection',
    'preheat': 'Preheating Active',
    'chilling': 'Chilling Active',
    'preheater_overheat': 'Preheater Overheat',
    'reheat': 'Reheating Active',
    'fireplace': 'Fireplace Mode Active',
    'underpressure_compensation': 'Underpressure Compensation',
    'external_boost': 'External Boost',
    'humidity_boost': 'Humidity Boost',
    'co2_boost': 'CO2 Boost',
    'defrosting': 'Defrosting Active',
    'defrost_starter': 'Defrost Starter',
    'tf_stop': 'Supply Fan Stop',
    'external_boost_function': 'External Boost Function',
    'external_fireplace_function': 'External Fireplace Function',
    'filter_guard_status': 'Filter Guard Status',
    'ir_freeze_protection': 'Heat Recovery Freeze Protection',
    'emergency_stop': 'Emergency Stop',
    'reheating_freezing_alarm': 'Reheater Freezing Alarm',
    'reheating_overheat_alarm': 'Reheater Overheat Alarm',
    'ir_sensor_failure': 'Heat Recovery Sensor Failure',
    'supply_fan_failure': 'Supply Fan Failure',
    'extract_fan_failure': 'Extract Fan Failure',
    'temperature_deviation_failure': 'Temperature Deviation Failure',
    'efficiency_alarm': 'Heat Recovery Efficiency Alarm',
    'filter_guard_alarm': 'Filter Guard Alarm',
    'service_reminder': 'Service Reminder',
    'temperature_failure': 'Temperature Sensor Failure',
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    hub = hass.data[DOMAIN]
    async_add_entities([CasaBinarySensor(hub, key) for key in FLAGS] + [
        CasaServiceStatus(hub, 'co2_control'),
        CasaServiceStatus(hub, 'external_control'),
    ] + [CasaFunctionStatus(hub, description) for description in SERVICE_FLAGS] + [
        CasaMenuStatus(hub, 'temperature_setting'),
        CasaMenuStatus(hub, 'week_schedule_enabled'),
    ])


class CasaFunctionStatus(CasaEntity, BinarySensorEntity):
    """Read-only function configuration, distinct from active alarm/status bits."""
    _attr_should_poll = False
    _attr_icon = 'mdi:cog-outline'

    def __init__(self, hub, description):
        self.hub, self.description = hub, description
        self._attr_unique_id = f'casa_premium_{hub.host}_{description.key}'
        configure_translation(self, hub)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.is_on is not None

    @property
    def is_on(self):
        return service_choice_value(self.hub, self.description)

    @property
    def extra_state_attributes(self):
        return {'source': f'0x{SERVICE_CONFIG[self.description.source][1]:02X}',
                'byte_offset': self.description.offset, 'read_only': True,
                'mapping_evidence': 'existing_code; physical_verification_pending'}

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaMenuStatus(CasaEntity, BinarySensorEntity):
    """Independent temperature-menu availability and week-schedule master."""
    _attr_should_poll = False

    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_unique_id = f'casa_premium_{hub.host}_{key}'
        configure_translation(self, hub)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.is_on is not None

    @property
    def is_on(self):
        if not self.hub.connected:
            return None
        return (self.hub.temperature_setting_enabled if self.key == 'temperature_setting'
                else self.hub.week_enabled)

    @property
    def extra_state_attributes(self):
        return {'source': '0x4D index 01' if self.key == 'temperature_setting' else '0x6F',
                'read_only': True,
                'mapping_evidence': 'existing_code; physical_verification_pending'}

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

class CasaBinarySensor(CasaEntity, BinarySensorEntity):
    _attr_should_poll = False
    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_unique_id = f'casa_premium_{hub.host}_{key}'
        configure_translation(self, hub)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)}, name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.key in self.hub.values

    @property
    def is_on(self):
        return self.hub.values.get(self.key)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaServiceStatus(CasaEntity, BinarySensorEntity):
    _attr_should_poll = False
    _attr_icon = 'mdi:cog-outline'

    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_unique_id = f'casa_premium_{hub.host}_service_{key}_status'
        configure_translation(self, hub)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        data = self.hub.service_value(self.key)
        if self.key == 'co2_control':
            return data is not None and data[3] in (1, 2)
        return data is not None

    @property
    def is_on(self):
        data = self.hub.service_value(self.key)
        if not self.available:
            return None
        return data[3] == 2 if self.key == 'co2_control' else bool(data[0] & 0x02)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))



async def async_setup_entry(hass, entry, async_add_entities):
    """Forwarded config-entry setup; preserve the same read-only entities."""
    await async_setup_platform(hass, {}, async_add_entities)


class CasaConnectionDiagnostic(CasaEntity, BinarySensorEntity):
    """Four independently observable receive-chain stages, including offline state."""
    _attr_should_poll = False
    _attr_entity_category = 'diagnostic'
    _attr_icon = 'mdi:lan-check'
    _NAMES = {'tcp': 'TCP-forbindelse', 'serial': 'Serielle råbytes',
              'telegram': 'CASA-telegrammer', 'fresh': 'Ferske sensordata'}

    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_name = self._NAMES[key]
        self._attr_unique_id = f'casa_premium_{hub.host}_connection_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return True  # Offline is a valid diagnostic state, not Unavailable.

    @property
    def is_on(self):
        if not self.hub.connected:
            return False
        if self.key == 'tcp':
            return True
        events = self.hub.diagnostic_events
        if not events:
            return False
        last = events[-1]
        from datetime import datetime, timezone
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last['timestamp'])).total_seconds()
        except (KeyError, ValueError, TypeError):
            return False
        if age > 60:
            return False
        if self.key == 'serial':
            return last['bytes'] > 0
        if self.key == 'telegram':
            return any(e['frames'] > 0 for e in list(events)[-50:])
        return any(e['sensor_keys'] for e in list(events)[-50:])

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))
