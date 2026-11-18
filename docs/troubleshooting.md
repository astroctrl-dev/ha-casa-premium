# Troubleshooting and maintenance

[← Back to CASA Premium](../README.md)

## Cannot connect to the gateway

Check that the host/IP is the converter's address, that the TCP port matches its listening port and that Home Assistant can reach it. Check local routing/firewall rules, transparent TCP server mode and client slots on the converter. Changing Home Assistant's port does not change the converter's listening port. Restart the converter only when required by its interface or diagnosis.

## Connected, but sensors are unavailable

Confirm the original panel works and that serial traffic reaches the converter. Check the [wiring and serial settings](hardware.md), including 38400/8N1 for the project R120 setup. A TCP connection can succeed even when serial data is absent or incompatible. Some values require their specific telegram type; use the [compatibility guide](supported-devices.md) when checking another model.

## Integration is missing after installation

Its runtime files should be under `custom_components/casa_premium/`. Perform a full Core restart and refresh the browser. Check **Settings → System → Logs** for `casa_premium` errors.

## No control buttons or clock setting

This is expected. The integration is read-only. The historical clock action is also blocked; use the original CASA panel. See [read-only behaviour](entities.md#read-only-behaviour).

## Update

1. Create a full Home Assistant backup and keep the complete previous integration directory/version.
2. Read the release notes. Updates to this read-only release do not restore legacy writable controls.
3. Select the intended release in Marketplace (or legacy HACS) and download it.
4. Save changes, validate Home Assistant's configuration and perform a full Core restart.
5. Check that the integration loads and your expected sensor values return.

## Restore a previous installation

If validation fails, do not restart into an invalid configuration. Restore the complete previous integration directory, removing files that belong only to the failed version, or restore the full backup. If configuration/registry data changed, use the corresponding full backup. Validate configuration, restart Core fully and check operation.

Marketplace/HACS can redownload a previous release only if that release exists; retain your own backup before first installation. Do not manually edit Home Assistant's `.storage` files.

## Uninstall

1. Remove the integration entry under **Settings → Devices & services**.
2. Remove the downloaded integration through Marketplace (or legacy HACS).
3. Remove any legacy YAML definition and save the change.
4. Validate configuration and restart Core fully.
5. Review automations and dashboards that referenced the removed sensors.

The manufacturer's original ventilation controls are not removed or replaced by uninstalling this integration.

## Report a problem

Include your Core version and Marketplace/HACS version where applicable, integration version, unit/controller model, relevant firmware and steps to reproduce it. Review and redact log excerpts before sharing. Never post credentials, tokens, private keys, private network addresses or full configuration exports.

Optional protocol logging writes local files when the existing `input_boolean.casa_ventilasjon_logging` helper is on. Those files can contain detailed device traffic. Do not upload them without reviewing their contents.
