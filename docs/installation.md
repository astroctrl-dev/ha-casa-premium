# Installation and configuration

[← Back to CASA Premium](../README.md)

## Before you start

- Check your [unit and controller](supported-devices.md).
- Wire and configure the [RS-485 to TCP/IP converter](hardware.md).
- Install HACS and use Home Assistant Core 2026.11.2 or later.
- Create a full Home Assistant backup. If replacing a previous integration, keep a copy of its complete integration directory too.

## Install through HACS

1. Open **HACS** and select **menu → Custom repositories**.
2. Enter `https://github.com/astroctrl-dev/ha-casa-premium` and select category **Integration**.
3. Add the repository, find **Swegon CASA Premium** and download the intended release.
4. Save configuration changes and run Home Assistant's configuration check. On HA OS: `ha core check`. If validation fails, stop and restore your backup.
5. Restart **Home Assistant Core** fully. On HA OS: `ha core restart`. A YAML reload is insufficient for installed Python files.

For a prerelease, enable prerelease/beta visibility in HACS and select that release explicitly. The project is a HACS Custom Repository; it is not listed in the HACS default catalogue.

## Add the connection

1. Open **Settings → Devices & services → Add integration**.
2. Search for **Swegon CASA Premium**.
3. Enter the converter's reachable IP address or hostname.
4. Enter its TCP listening port: **8899** by default.
5. Select **Submit**.

![Illustrative gateway setup form](images/casa-gateway-setup.svg)

The hostname in this illustration is an example, not a device on your network. Enter the converter's address, not Home Assistant's address. Once matching serial traffic arrives, sensor entities will have values. A successful TCP connection alone does not confirm correct serial wiring or protocol data.

## Change the IP address or port

Open **Settings → Devices & services → Swegon CASA Premium → Configure/Options**. Change the desired fields and save. Invalid values or failed connection probes are rejected; the previous saved settings remain in place. A valid change reloads the connection.

Do not delete and recreate the integration just to change the endpoint. Do not configure the same gateway simultaneously through YAML and the GUI. Existing YAML support remains for compatibility; the GUI is the recommended setup path.

## What is configured where?

| Setting | Configure it in |
| --- | --- |
| Converter network address and TCP server/listening port | Converter's configuration interface |
| Serial baud rate, parity, data/stop bits and flow control | Converter's configuration interface |
| Address/hostname and TCP port used by Home Assistant | Integration's setup or Configure/Options form |

Changing a field in Home Assistant does not reconfigure the converter. See [hardware settings](hardware.md) for the 38400/8N1 project profile and local-network prerequisites.

For updates, restore and removal, see [maintenance](troubleshooting.md#update).
