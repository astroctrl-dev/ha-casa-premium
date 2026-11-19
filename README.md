# CASA Premium

Bring your Swegon CASA Premium ventilation into Home Assistant.

**Local connection · Read-only monitoring · GUI configuration**

Monitor temperatures, fan information and ventilation status from Home Assistant through an RS-485 to TCP/IP converter. Your original CASA controller continues to operate the ventilation system.

This is an unofficial community integration. It does not send control or clock-setting commands.

## Features

* **Temperatures at a glance** — outdoor, supply, extract and exhaust readings, where provided by your unit.
* **Fan information** — view available supply/extract fan data and operating status.
* **Status and alarms** — see the ventilation mode, reported functions and alarm indicators.
* **Readable service settings** — inspect available settings without changing the unit.
* **Local operation** — the integration connects directly to your converter; no cloud account is required for monitoring.
* **Your language** — English, Norwegian Bokmål and Norwegian Nynorsk for names, states and setup dialogs.
* **Your temperature unit** — Celsius or Fahrenheit using Home Assistant's temperature settings, including temperature differences.
* **Setup in the UI** — enter the converter’s address and port, and change them later from Configure/Options. No YAML is required for GUI setup.

The available entities depend on the connected unit, firmware and received telegrams. One active gateway is supported per Home Assistant instance. Read-only monitoring of the same CASA system has been tested with two Home Assistant instances.

## What You Need

| Component | Requirement |
| --- | --- |
| Ventilation unit | Swegon CASA R120 with Premium controller is the tested project installation. Compatibility is confirmed for this project installation; other model/controller combinations may differ. |
| Converter | RS-485 to TCP/IP, configured as a transparent TCP server |
| Serial connection | Tested R120 configuration: 38400 baud, 8N1, no hardware flow control |
| Home Assistant | Requires Core 2026.11.2 or later; project verification baseline is 2026.11.2. |
| Installation | Home Assistant Marketplace on Core 2026.11 and later; legacy HACS menus are documented separately |
| Network | Home Assistant must be able to reach the converter’s local IP address and TCP port, normally 8899 |

Prepare the hardware using the [wiring and converter guide](docs/hardware.md).

Keep the original CASA control panel connected so that the required serial communication remains available.

## Installation with Marketplace / HACS

1. Create a Home Assistant backup.
2. On Home Assistant Core 2026.11 and later, open **Settings → Marketplace → Add from link**.
3. Enter `https://github.com/astroctrl-dev/ha-casa-premium`, select **Add**, and choose **Integration** if asked.
4. Open **Swegon CASA Premium**, select the intended release and install it.
5. Follow any restart prompt. For this release, validate your Home Assistant configuration and perform a full Home Assistant Core restart before setup.
6. Navigate to **Settings → Devices & services → Add integration**.
7. Search for **Swegon CASA Premium**.
8. Enter the IP address or hostname of your RS-485 converter and its TCP port, normally **8899**.
9. Select **Submit** to complete the configuration.

On older installations still using HACS, use **HACS → Menu → Custom repositories** and add the same URL as an **Integration**. Earlier Home Assistant versions have not been tested; release metadata currently requires Core 2026.11.2. This project is added from a link and is not included in the default catalogue.

Your sensors will appear once the converter supplies matching CASA telegrams.

To change the IP address or port later, open the integration’s Configure/Options dialog.

See the [installation guide](docs/installation.md) for more information.

## Documentation

| Guide | Description |
| --- | --- |
| [Installation and configuration](docs/installation.md) | Marketplace/HACS installation, initial setup and connection settings |
| [Wiring and converter settings](docs/hardware.md) | RJ12 connector, RS-485 wiring and converter configuration |
| [Supported devices](docs/supported-devices.md) | Tested hardware and known compatibility limitations |
| [Sensors and everyday use](docs/entities.md) | Available sensor information and how to use it |
| [Troubleshooting and maintenance](docs/troubleshooting.md) | Connection issues, updates, restoring and uninstalling |
| [Diagnostics – CASA Live Analysis](casa_live_analysis/README.md) | Optional Home Assistant app for live connection metrics, automatic communication analysis, 15-minute capture and CSV export (app v1.0.0 requires CASA Premium integration v1.3.0 or later with diagnostics API) |

## Support and Contributions

CASA Premium is a community-driven project maintained on a best-effort basis.

There is no guaranteed support, response time or commitment to fix reported issues.

If you encounter a problem:

1. Check the [troubleshooting guide](docs/troubleshooting.md).
2. Search existing [GitHub Issues](https://github.com/astroctrl-dev/ha-casa-premium/issues) for similar problems and solutions.
3. Investigate the problem and, where possible, propose a solution.
4. Open a GitHub Issue with relevant technical details if the problem remains unresolved.
5. Contributions and pull requests with proposed fixes are welcome.

Users are encouraged to help each other, share solutions and contribute improvements.

Please remove credentials, personal information and sensitive network details from logs before sharing them.

## Disclaimer

**Unofficial integration — use entirely at your own risk.**

CASA Premium is an independent, community-developed integration. It is not affiliated with, endorsed by or officially supported by Swegon.

You are solely responsible for assessing the risks associated with installing, connecting, configuring and using this integration.

### Electrical and Hardware Safety

Connecting an RS-485 converter to a ventilation system involves electrical and hardware-related risks.

Incorrect wiring, voltage levels or connections may damage the ventilation unit, converter or other connected equipment, and may create safety hazards.

You are responsible for verifying the electrical specifications, connector pinout, voltage levels and compatibility of your equipment before making any connections.

Do not perform electrical work unless you are qualified and legally permitted to do so. Consult a qualified professional when necessary.

### Software and Operational Risks

The software is provided “AS IS”, without warranties of any kind, to the extent permitted by applicable law.

You are responsible for evaluating the suitability, security, reliability and potential consequences of installing and running the software.

Although the integration is designed for read-only monitoring, errors, unexpected behaviour, inaccurate sensor readings or compatibility issues may occur.

This integration must not be relied upon for safety-critical monitoring or control.

Always retain the manufacturer’s original controls and safety mechanisms.

By choosing to install or use this integration, you accept responsibility for evaluating and managing the associated risks.

## Project Origins

The [openHAB Swegon Ventilation Binding](https://github.com/openhab/openhab1-addons/wiki/Swegon-Ventilation-Binding) provided valuable initial information about the Swegon CASA serial communication protocol, including the telegram framing format.

Building on this knowledge, we captured serial communication from a CASA ventilation unit and analysed the received telegrams by comparing their contents with actual operating conditions and measured values.

This process helped us identify message types, data fields and sensor values, forming the foundation for the CASA Premium integration for Home Assistant.

We acknowledge and appreciate the earlier work of the openHAB community.

## Languages and temperature units

English, Norwegian Bokmål and Norwegian Nynorsk are included. Entity names use Home Assistant's server language when created; states and dialogs use the interface language. Existing entity IDs and manually assigned names are preserved. English is the fallback for other languages.

Temperature values follow Home Assistant's Celsius/Fahrenheit setting; an explicit unit choice on an individual sensor takes priority. See [languages and units](docs/languages-and-units.md) for details and automation considerations.
