# Supported devices

[← Back to CASA Premium](../README.md)

This integration uses the **CASA Premium serial protocol** through an RS-485 to TCP/IP converter. A product carrying the CASA name is not automatically compatible.

| Unit/controller | Compatibility |
| --- | --- |
| **Swegon CASA R120 with Premium controller** | Tested project installation for read-only monitoring |
| Other CASA units with a Premium controller/protocol | Not yet verified; compatibility is not promised |
| CASA Smart or other controller/protocol families | Outside this release's documented compatibility scope |

The R120 wiring and serial profile are documented in the [hardware guide](hardware.md). They are project references, not a universal manufacturer pinout. Firmware variants have not been catalogued into a compatibility matrix.

## Software and connection

| Component | Supported baseline |
| --- | --- |
| Home Assistant Core | Minimum 2026.11.2; this is the tested baseline |
| HACS | Required for the documented HACS installation path |
| Connection | Local transparent TCP server forwarding CASA RS-485 traffic |
| Serial profile for the project R120 setup | 38400 baud, 8 data bits, no parity, 1 stop bit, no CTS/RTS |
| Number of active gateways | One |

Newer Core releases may introduce compatibility changes. The integration cannot guarantee every unit/firmware/converter combination. Sensor availability depends on the telegrams actually received, and some service fields may be absent or differ across firmware.

If you would like to report another model, open an issue with the unit/controller model, firmware versions if known, converter type and a description of the values that work. Do not post private network addresses or raw unreviewed logs. A model is not added as supported solely because a TCP connection succeeds.
