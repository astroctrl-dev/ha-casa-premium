# Languages and temperature units

[← Back to CASA Premium](../README.md)

## Languages

| Home Assistant language | CASA Premium text |
| --- | --- |
| English / English (GB) | English |
| Norsk bokmål | Norwegian Bokmål |
| Norsk nynorsk | Norwegian Nynorsk |
| Other languages | English fallback |

Configuration dialogs, error messages, enum states and supported attribute labels use the interface translations. For example, the internal mode `Home` is displayed as **Home**, **Hjemme** or **Heime**. Raw states, protocol values, attribute keys and unique IDs remain stable.

Entity names follow Home Assistant's server-language behavior at creation. Changing the interface language does not automatically rename existing entities. Manually assigned entity or dashboard-card names remain under your control. No separate CASA language selector is needed.

## Celsius and Fahrenheit

Choose your temperature unit under **Settings → System → Home information**. Ordinary temperatures and service temperature limits/setpoints follow the Home Assistant unit setting. An explicit unit override in an individual sensor's settings takes priority. No reinstallation or delete/re-add is required.

The converter and CASA protocol still use their original values. Changing a display unit sends no ventilation-control or clock-setting commands.

| Value type | Celsius example | Fahrenheit display |
| --- | --- | --- |
| Absolute temperature / setpoint | 20 °C | 68 °F |
| Temperature difference / deviation | 2 °C | 3.6 °F |

The summer-night cooling temperature difference and SA setpoint deviation are intervals: they are scaled without adding 32. Their selected unit can change after installation. Percentages, RPM, ppm thresholds and time intervals are independent of the temperature unit.

Home Assistant's numeric sensor state changes together with its unit. Automations or templates containing fixed numeric temperature thresholds must account for the selected unit. Use the entity's actual unit rather than assuming every reading remains Celsius.

## Setpoint names

The main **Supply Air Temperature Setpoint** is separate from **Afterheating Supply Setpoint (Unverified)**, a legacy status field. The latter label distinguishes the source; it does not establish the field as a confirmed physical setpoint. Keep the original CASA controller as the reference for operating settings.
