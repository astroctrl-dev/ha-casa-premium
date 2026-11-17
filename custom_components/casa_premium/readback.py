"""Numeric readback mappings inherited from the existing control platforms.

These describe the current parser, not new verification against a physical unit.
Write-side UI bounds are deliberately not treated as readback validity rules.
"""
from dataclasses import dataclass

from . import SERVICE_CONFIG, SERVICE_FAN_PROFILES, COOLING_FAN_LABELS


@dataclass(frozen=True)
class NumericReadback:
    key: str
    name: str
    source: str
    offset: int
    unit: str | None = None
    width: int = 1
    divisor: int = 1


SERVICE_NUMBERS = (
    *(
        NumericReadback(f'service_{source}_{level}',
                        f'Service {label} Fan Level {level}', source, level - 1, '%')
        for source, label in (('supply_fan', 'Supply'), ('extract_fan', 'Extract'))
        for level in range(1, 6)
    ),
    *(
        NumericReadback(f'service_profile_{index}', f'Service Fan Profile {label}',
                        'fan_profiles', index)
        for index, label in enumerate(SERVICE_FAN_PROFILES)
    ),
    NumericReadback('functions_service_interval_months', 'Functions Service Reminder Interval',
                    'service_interval', 0, 'months'),
    NumericReadback('functions_summer_night_cooling_temperature_difference',
                    'Functions Summer Night Cooling Temperature Difference',
                    'summer_night_cooling', 3, '°C'),
    NumericReadback('functions_summer_night_cooling_temperature_limit',
                    'Functions Summer Night Cooling Temperature Limit',
                    'summer_night_cooling', 2, '°C'),
    NumericReadback('functions_heating_temperature_limit', 'Functions Heating Temperature Limit',
                    'heating', 1, '°C'),
    *(
        NumericReadback(f'functions_heating_{parameter}',
                        f'Functions Heating Supply Controller {parameter.upper()}',
                        'heating', offset, width=2, divisor=100)
        for parameter, offset in (('p', 3), ('i', 5), ('d', 7))
    ),
    NumericReadback('functions_filter_monitor_delay', 'Functions Filter Monitor Delay',
                    'filter_monitor', 1, 'min'),
    NumericReadback('functions_sa_limit_minimum_supply_temperature',
                    'Functions SA Limit Minimum Supply Temperature', 'sa_limit', 0, '°C'),
    NumericReadback('functions_sa_limit_setpoint_difference',
                    'Functions SA Limit Setpoint Difference', 'sa_limit', 1, '°C'),
    NumericReadback('functions_electric_air_heater_temperature_temperature_setpoint',
                    'Functions Electric Air Heater Temperature Setpoint',
                    'electric_air_heater_temperature', 4, '°C'),
    NumericReadback('summer_cooling_temperature', 'Summer Cooling Temperature',
                    'summer_night_cooling', 1, '°C'),
)


def service_number_value(hub, description):
    """Require full unit readback; never initiate a request or write."""
    data = hub.service_value(description.source)
    size = SERVICE_CONFIG[description.source][2]
    if data is None or len(data) != size:
        return None
    value = int.from_bytes(data[description.offset:description.offset + description.width], 'big')
    return value if description.divisor == 1 else value / description.divisor


@dataclass(frozen=True)
class ChoiceReadback:
    key: str
    name: str
    source: str
    offset: int
    choices: tuple[tuple[int, bool | str], ...]


ON_OFF = ((1, False), (2, True))
SERVICE_FLAGS = (
    ChoiceReadback('functions_service_reminder', 'Functions Service Reminder',
                   'service_reminder', 1, ON_OFF),
    ChoiceReadback('functions_summer_night_cooling', 'Functions Summer Night Cooling',
                   'summer_night_cooling', 0, ON_OFF),
    ChoiceReadback('functions_heating', 'Functions Heating', 'heating', 0, ON_OFF),
    ChoiceReadback('functions_filter_monitor', 'Functions Filter Monitor',
                   'filter_monitor', 0, ON_OFF),
    ChoiceReadback('functions_fireplace_function', 'Functions Fireplace Function Configuration',
                   'fireplace_function', 3, ON_OFF),
    ChoiceReadback('functions_boost_special', 'Functions Boost Special Configuration',
                   'boost_special', 1, ON_OFF),
    ChoiceReadback('functions_electric_air_heater', 'Functions Electric Air Heater',
                   'electric_air_heater', 4, ON_OFF),
    ChoiceReadback('service_weekly_schedule', 'Service Weekly Schedule Menu Available',
                   'weekly_schedule', 3, ((0, False), (1, False), (2, True))),
)
SERVICE_CHOICES = (
    ChoiceReadback('summer_cooling_fan', 'Summer Cooling Fan', 'summer_night_cooling',
                   4, tuple(COOLING_FAN_LABELS.items())),
    ChoiceReadback('functions_heating_control', 'Functions Heating Control',
                   'heating', 2, ((0, 'Supply'), (1, 'Extract'))),
)


def service_choice_value(hub, description):
    """Unknown codes are unavailable, never silently interpreted as off."""
    data = hub.service_value(description.source)
    if data is None or len(data) != SERVICE_CONFIG[description.source][2]:
        return None
    return dict(description.choices).get(data[description.offset])
