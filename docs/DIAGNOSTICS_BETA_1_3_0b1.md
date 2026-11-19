# CASA Premium v1.3.0b1 – diagnostics integration candidate

This branch adds passive measurement to the existing single TCP receiver. No analysis app is needed.

## Read-only API

Connect to Home Assistant's authenticated WebSocket endpoint `/api/websocket` using the normal HA authentication handshake, then send:

```json
{"id": 1, "type": "casa_premium/diagnostics", "after": 0}
```

The response includes `connected`, aggregate `health` counters, `latest_seq`, `oldest_seq`, `lost`, and `events`. Each event has a sequence number, UTC observation timestamp, event type and elapsed milliseconds since the previous recorded event. Types are `tcp_receive` (byte count), `crc_error` (count), `telegram` (command and length), and `sensor_observation` (command and sensor keys). Subsequent requests should use the last seen sequence as `after`. Maximum retained events: 4096. If `lost > 0`, events have been overwritten.

**Limitations:** Timestamps represent observations inside HA, not physical RS-485 wire timing. `tcp_receive` bytes are gateway-delivered serial payload, not proof of individual serial byte timestamps. Unrecognized but CRC-valid frames may have no decoded sensor values. No raw frame bytes are exposed.

## Candidate verification – not yet completed

- Syntax/import checks on exact commit
- Regression tests for TCP receive, parsing, existing sensors and read-only behavior without app
- WebSocket authentication and pagination/overflow checks
- 15-minute capture with a test client, and reconnect/disconnect behavior
- Runtime verification on an authorized test HA environment
- Rollback to unchanged v1.2.0

No changes to HA-DEV or HA-Hoved are authorized by this candidate.
