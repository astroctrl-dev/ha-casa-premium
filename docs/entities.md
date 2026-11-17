# Sensors and everyday use

[← Back to CASA Premium](../README.md)

Open **Settings → Devices & services → Swegon CASA Premium** to find the integration's entities. Add the sensors you use to a Home Assistant dashboard with the standard entity or tile cards.

| Category | Available information, when supplied by the unit |
| --- | --- |
| Temperatures | Outdoor, supply, extract and exhaust readings |
| Fans | Supply/extract fan information and operating status |
| Ventilation | Reported operating mode and active functions |
| Alarms | Reported alarm and fault indicators |
| Service settings | Readable configuration values reported in supported telegrams |

Not every unit or firmware supplies every value. Some fields update only when the corresponding telegram arrives. Missing values can be unavailable, and values can be delayed or inaccurate. Do not rely on these sensors for safety-related decisions.

## Read-only behaviour

This integration exposes sensor and binary-sensor entities. It does not create controls to change fan mode, temperatures or other unit settings. There is no write-enable option. Use the original CASA controller for control and clock settings.

The legacy `casa_premium.sync_clock` action may remain visible in Developer Tools with its historical description. It is a compatibility stub: calls are rejected as read-only and do not set the clock.

If upgrading from an older writable integration, review automations that depended on its control entities. They cannot regain write functionality through this release.
