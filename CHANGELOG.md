# Changelog

## 1.2.0b2 — pre-release

- Added automatic read-only communication diagnostics on the CASA device: TCP, incoming bytes, decoded telegrams and fresh sensor coverage.
- Added timestamps, data age, reasons and colored status symbols with text in English, Bokmål and Nynorsk.
- Kept the existing config entry and sensor IDs. No control commands are sent.

## 1.1.0

- Added English, Norwegian Bokmål and Norwegian Nynorsk translations for sensor names, states and configuration dialogs.
- Added Celsius/Fahrenheit support for service temperature settings, including correct conversion of temperature differences.
- Clarified the afterheating supply-setpoint sensor name to distinguish it from the main supply-air temperature setpoint.
- Preserved existing entity IDs, configuration and read-only operation.

## 1.0.0

- Local read-only monitoring for the documented CASA Premium connection.
- GUI setup and later host/port changes.
- Temperature, fan, status and readable service-value sensors.
- English installation, compatibility and wiring guides.
