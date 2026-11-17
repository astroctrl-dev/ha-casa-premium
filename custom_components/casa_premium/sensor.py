"""CASA read-only numeric sensors."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN, SERVICE_CONFIG
from .readback import SERVICE_NUMBERS, SERVICE_CHOICES, service_number_value, service_choice_value

TEMPERATURES = ('outdoor_temp','supply_temp','extract_temp','supply_temp_heated','t5','t6','t7','exhaust_temp','afterheating_supply_setpoint','afterheating_room_setpoint')
TEMP_NAMES = {
    'outdoor_temp': 'T1 · Outdoor Air Temperature',
    'supply_temp': 'T2 · Supply Air / Frost Protection',
    'extract_temp': 'T3 · Extract Air Temperature',
    'supply_temp_heated': 'T4 · Supply Air After Heating',
    't5': 'T5 · Exhaust Air After Heat Exchanger',
    't6': 'T6 · Reheater Overtemperature Sensor',
    't7': 'T7 · Raw Temperature Value',
    'exhaust_temp': 'T8 · Room Temperature',
}

OTHER_NAMES = {
    'afterheating_supply_setpoint': 'Supply Air Temperature Setpoint',
    'afterheating_room_setpoint': 'Room Temperature Setpoint',
    'supply_fan_rpm': 'Supply Fan RPM',
    'extract_fan_rpm': 'Extract Fan RPM',
    'fan_speed': 'Fan Speed',
    'supply_fan_virtual_speed': 'Supply Fan Virtual Speed',
    'extract_fan_virtual_speed': 'Extract Fan Virtual Speed',
    'efficiency': 'Heat Recovery Efficiency',
    'efficiency_supply_calc': 'Supply Air Efficiency (Calculated)',
    'efficiency_extract_calc': 'Extract Air Efficiency (Calculated)',
    'co2': 'CO2',
    'humidity': 'Relative Humidity',
    'operating_mode': 'Operating Mode',
    'unit_state': 'Unit State',
    'unit_status': 'Unit Status',
    'model': 'Model',
    'firmware_rc': 'Firmware RC',
    'firmware_fst': 'Firmware FST',
}
RPM = ('supply_fan_rpm','extract_fan_rpm')
PERCENT = ('efficiency','efficiency_supply_calc','efficiency_extract_calc')
OTHER = ('co2','humidity','operating_mode','unit_state','fan_speed','supply_fan_virtual_speed','extract_fan_virtual_speed','unit_status')
IDENTIFICATION = ('model', 'firmware_rc', 'firmware_fst')
KEYS = TEMPERATURES + RPM + PERCENT + OTHER + IDENTIFICATION

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    hub = hass.data[DOMAIN]
    async_add_entities([CasaSensor(hub, key) for key in KEYS] + [CasaActualModeSensor(hub)] + [CasaClockSensor(hub, key) for key in ("clock", "weekday", "clock_drift")] + [CasaUnknownTemperatureIndex01(hub)] +
                       [CasaCo2ThresholdSensor(hub, index) for index in (0, 1)] +
                       [CasaServiceNumberSensor(hub, description) for description in SERVICE_NUMBERS] +
                       [CasaSupplySetpointSensor(hub)] +
                       [CasaServiceChoiceSensor(hub, description) for description in SERVICE_CHOICES])


class CasaServiceChoiceSensor(SensorEntity):
    """Observed menu choice without a selectable control."""
    _attr_should_poll = False
    _attr_icon = 'mdi:cog-outline'

    def __init__(self, hub, description):
        self.hub, self.description = hub, description
        self._attr_name = 'CASA ' + description.name
        self._attr_unique_id = f'casa_premium_{hub.host}_{description.key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.native_value is not None

    @property
    def native_value(self):
        return service_choice_value(self.hub, self.description)

    @property
    def extra_state_attributes(self):
        return {'source': f'0x{SERVICE_CONFIG[self.description.source][1]:02X}',
                'byte_offset': self.description.offset, 'read_only': True,
                'mapping_evidence': 'existing_code; physical_verification_pending'}

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaServiceNumberSensor(SensorEntity):
    """Observed configuration value; deliberately has no write method."""
    _attr_should_poll = False
    _attr_icon = 'mdi:cog-outline'

    def __init__(self, hub, description):
        self.hub, self.description = hub, description
        self._attr_name = 'CASA ' + description.name
        self._attr_unique_id = f'casa_premium_{hub.host}_{description.key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')
        if description.unit:
            self._attr_native_unit_of_measurement = description.unit

    @property
    def available(self):
        return self.native_value is not None

    @property
    def native_value(self):
        return service_number_value(self.hub, self.description)

    @property
    def extra_state_attributes(self):
        from . import SERVICE_CONFIG
        return {
            'source': f'0x{SERVICE_CONFIG[self.description.source][1]:02X}',
            'byte_offset': self.description.offset,
            'byte_width': self.description.width,
            'divisor': self.description.divisor,
            'read_only': True,
            'mapping_evidence': 'existing_code; physical_verification_pending',
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaSupplySetpointSensor(SensorEntity):
    """0x4D index 0 setpoint, independent of the index 1 menu status."""
    _attr_should_poll = False
    _attr_name = 'CASA Supply Air Temperature Setpoint'
    _attr_native_unit_of_measurement = '°C'
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_supply_air_temperature_setpoint'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.supply_air_setpoint_data is not None

    @property
    def native_value(self):
        return self.hub.supply_air_temperature_setpoint if self.available else None

    @property
    def extra_state_attributes(self):
        return {'source': '0x4D', 'telegram_index': '00', 'read_only': True,
                'mapping_evidence': 'existing_code; physical_verification_pending'}

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))

class CasaSensor(SensorEntity):
    _attr_should_poll = False
    def __init__(self, hub, key):
        self.hub, self.key = hub, key
        self._attr_name = 'CASA ' + TEMP_NAMES.get(key, OTHER_NAMES.get(key, key.replace('_', ' ').title()))
        self._attr_unique_id = f'casa_premium_{hub.host}_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)}, name='Swegon CASA Premium', manufacturer='Swegon')
        if key in TEMPERATURES:
            self._attr_native_unit_of_measurement = '°C'
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        elif key in RPM:
            self._attr_native_unit_of_measurement = 'rpm'
        elif key in PERCENT:
            self._attr_native_unit_of_measurement = '%'
        elif key == 'humidity':
            self._attr_native_unit_of_measurement = '%'
            self._attr_device_class = SensorDeviceClass.HUMIDITY
        if key in TEMPERATURES + RPM + PERCENT + ('humidity',):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self):
        return self.hub.connected and self.hub.values.get(self.key) is not None

    @property
    def native_value(self):
        return self.hub.values.get(self.key)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaActualModeSensor(SensorEntity):
    """Confirmed real mode from two consecutive 0x73 status frames."""
    _attr_should_poll = False
    _attr_name = 'CASA Ventilation Mode Actual'
    _attr_icon = 'mdi:hvac'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_mode_actual'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)}, name='Swegon CASA Premium',
            manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.connected and self.hub.actual_mode is not None

    @property
    def native_value(self):
        return self.hub.actual_mode

    @property
    def extra_state_attributes(self):
        return {
            'source': '0x73',
            'boost_duration_minutes': self.hub.actual_boost_minutes,
            'sync_status': self.hub.mode_sync_status,
            'pending_mode': self.hub.pending_mode,
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaClockSensor(SensorEntity):
    """Read-only diagnostics from unsolicited CASA 0x55 clock reports."""
    _attr_should_poll = False

    def __init__(self, hub, key):
        self.hub = hub
        self.key = key
        names = {
            "clock": "CASA Clock",
            "weekday": "CASA Weekday",
            "clock_drift": "CASA Clock Drift",
        }
        self._attr_name = names[key]
        self._attr_unique_id = f"casa_premium_{hub.host}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name="Swegon CASA Premium",
            manufacturer="Swegon",
        )
        if key == "clock":
            self._attr_icon = "mdi:clock-outline"
        elif key == "weekday":
            self._attr_icon = "mdi:calendar-week"
        else:
            self._attr_icon = "mdi:timer-outline"
            self._attr_native_unit_of_measurement = "s"
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self):
        return (
            self.hub.connected
            and self.hub.clock_data is not None
            and self.hub.clock_observed_at is not None
        )

    @property
    def native_value(self):
        if not self.available:
            return None
        weekday, hour, minute, second = self.hub.clock_data
        if self.key == "clock":
            return f"{hour:02d}:{minute:02d}:{second:02d}"
        if self.key == "weekday":
            return ("Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday")[weekday]
        from . import clock_drift_seconds
        return clock_drift_seconds(
            self.hub.clock_data, self.hub.clock_observed_at
        )

    @property
    def extra_state_attributes(self):
        if not self.available:
            return {}
        return {
            "source": "0x55",
            "observed_at": self.hub.clock_observed_at.isoformat(),
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaUnknownTemperatureIndex01(SensorEntity):
    """Unidentified 0x4D index 01 temperature; read-only diagnostic."""
    _attr_should_poll = False
    _attr_name = 'CASA Temperature Index 01 (Ukjent)'
    _attr_native_unit_of_measurement = '°C'
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = 'mdi:help-circle-outline'

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f'casa_premium_{hub.host}_temperature_index_01_unknown'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.host)},
            name='Swegon CASA Premium',
            manufacturer='Swegon',
        )

    @property
    def available(self):
        return self.hub.connected and self.hub.temperature_setting_data is not None

    @property
    def native_value(self):
        if not self.available:
            return None
        return self.hub.temperature_setting_data[1] / 10.0

    @property
    def extra_state_attributes(self):
        return {
            'source': '0x4D',
            'telegram_index': '01',
            'status': 'Ukjent – ikke identifisert i betjeningspanelet',
            'read_only': True,
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))


class CasaCo2ThresholdSensor(SensorEntity):
    _attr_should_poll = False
    _attr_native_unit_of_measurement = 'ppm'
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = 'mdi:molecule-co2'

    def __init__(self, hub, index):
        self.hub, self.index = hub, index
        name = 'Home' if index == 0 else 'Boost'
        self._attr_name = f'CASA Service CO2 {name} Threshold'
        self._attr_unique_id = f'casa_premium_{hub.host}_service_co2_threshold_{name.lower()}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.host)},
                                            name='Swegon CASA Premium', manufacturer='Swegon')

    @property
    def available(self):
        return self.hub.service_value('co2_control') is not None

    @property
    def native_value(self):
        data = self.hub.service_value('co2_control')
        return data[self.index] * 10 if data else None

    async def async_added_to_hass(self):
        self.async_on_remove(self.hub.subscribe(self.async_write_ha_state))



async def async_setup_entry(hass, entry, async_add_entities):
    """Forwarded config-entry setup; preserve the same read-only entities."""
    await async_setup_platform(hass, {}, async_add_entities)
