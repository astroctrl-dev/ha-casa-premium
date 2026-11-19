"""Passive communication health for the single CASA TCP receiver.

A TCP connection is not evidence of serial bytes, a CRC-valid frame is not
necessarily a decoded reading, and a reading is only fresh for its own field.
The thresholds are provisional until observed against the physical gateway.
"""
from datetime import datetime, timezone

RAW_FRESH_SECONDS = 5
FRAME_FRESH_SECONDS = 120
SENSOR_FRESH_SECONDS = 120
STARTUP_GRACE_SECONDS = 15

# Core 0x71 measurements; service and identification telegrams are irregular
# and therefore excluded from the percentage denominator.
EXPECTED_SENSORS = (
    "outdoor_temp", "supply_temp", "extract_temp", "supply_temp_heated",
    "exhaust_temp", "supply_fan_rpm", "extract_fan_rpm",
    "efficiency", "co2", "humidity",
)
CRITICAL_SENSORS = (
    "outdoor_temp", "supply_temp", "extract_temp", "supply_temp_heated",
    "supply_fan_rpm", "extract_fan_rpm",
)


def age_seconds(when, now):
    if when is None:
        return None
    return max(0, int((now - when).total_seconds()))


def health(hub, now=None):
    """Return four independent states and evidence for HA diagnostic entities.

    States: ok, degraded, error, waiting, not_measurable. On restart the
    in-memory evidence begins in waiting; no persisted green state is trusted.
    """
    now = now or datetime.now(timezone.utc)
    connected = hub.connected
    startup_age = age_seconds(getattr(hub, 'diagnostic_started_at',
                                      hub.diagnostic_connected_at), now)
    raw_age = age_seconds(hub.diagnostic_last_byte_at, now)
    frame_age = age_seconds(hub.diagnostic_last_frame_at, now)
    decoded_age = age_seconds(hub.diagnostic_last_decoded_at, now)
    # Historical timestamps remain visible, but never prove data on the new socket.
    active_raw_age = raw_age if (hub.diagnostic_last_byte_at is not None
        and hub.diagnostic_connected_at is not None
        and hub.diagnostic_last_byte_at >= hub.diagnostic_connected_at) else None
    active_frame_age = frame_age if (hub.diagnostic_last_frame_at is not None
        and hub.diagnostic_connected_at is not None
        and hub.diagnostic_last_frame_at >= hub.diagnostic_connected_at) else None
    active_decoded_age = decoded_age if (hub.diagnostic_last_decoded_at is not None
        and hub.diagnostic_connected_at is not None
        and hub.diagnostic_last_decoded_at >= hub.diagnostic_connected_at) else None
    fresh = tuple(key for key in EXPECTED_SENSORS
                  if connected and key in hub.values
                  and (age_seconds(hub.diagnostic_sensor_seen.get(key), now) is not None)
                  and age_seconds(hub.diagnostic_sensor_seen[key], now) <= SENSOR_FRESH_SECONDS)
    coverage = round(100 * len(fresh) / len(EXPECTED_SENSORS)) if connected else None
    missing_critical = (tuple(key for key in CRITICAL_SENSORS if key not in fresh)
                        if connected else ())

    if not connected:
        tcp = "error" if hub.diagnostic_last_error else "waiting"
        raw = frame = sensor = "not_measurable"
    else:
        tcp = "ok"
        if active_raw_age is None:
            raw = "waiting" if startup_age is None or startup_age < STARTUP_GRACE_SECONDS else "error"
        else:
            raw = "ok" if active_raw_age < RAW_FRESH_SECONDS else "error"
        if active_frame_age is None:
            frame = "waiting" if startup_age is None or startup_age < STARTUP_GRACE_SECONDS else "error"
        else:
            frame = "ok" if active_frame_age <= FRAME_FRESH_SECONDS else "error"
        if not hub.diagnostic_sensor_seen and (startup_age is None or startup_age < STARTUP_GRACE_SECONDS):
            sensor = "waiting"
        elif len(fresh) == len(EXPECTED_SENSORS):
            sensor = "ok"
        elif fresh:
            sensor = "degraded"
        else:
            sensor = "error"
        # Only successfully decoded telegrams prove protocol communication.
        if active_decoded_age is None or active_decoded_age > FRAME_FRESH_SECONDS:
            if frame != "waiting":
                frame = "degraded" if active_raw_age is not None and active_raw_age < RAW_FRESH_SECONDS else "error"
    reasons = {
        "tcp": hub.diagnostic_last_error if not connected and hub.diagnostic_last_error else
               ("connected" if connected else "awaiting_connection"),
        "raw_bytes": "tcp_unavailable" if not connected else
                     ("no_traffic" if active_raw_age is None else
                      "stale_traffic" if active_raw_age >= RAW_FRESH_SECONDS else "receiving"),
        "telegram": "tcp_unavailable" if not connected else
                    ("no_valid_frames" if active_frame_age is None else
                     "no_decoded_data" if active_decoded_age is None else
                     "stale_telegrams" if active_decoded_age > FRAME_FRESH_SECONDS else "decoded"),
        "sensors": "tcp_unavailable" if not connected else
                   ("no_fresh_sensors" if not fresh else
                    "partial_fresh_sensors" if len(fresh) < len(EXPECTED_SENSORS) else "fresh"),
    }
    return {
        "reasons": reasons,
        "tcp": tcp, "raw_bytes": raw, "telegram": frame,
        "sensors": sensor, "coverage_percent": coverage,
        "fresh_sensors": len(fresh), "expected_sensors": len(EXPECTED_SENSORS),
        "missing_critical": missing_critical,
        "raw_age_seconds": raw_age, "frame_age_seconds": frame_age,
        "decoded_age_seconds": decoded_age,
        "last_byte_at": hub.diagnostic_last_byte_at,
        "last_frame_at": hub.diagnostic_last_frame_at,
        "last_decoded_at": hub.diagnostic_last_decoded_at,
        "last_error": hub.diagnostic_last_error,
        "received_bytes": hub.diagnostic_received_bytes,
        "valid_frames": hub.diagnostic_valid_frames,
        "decoded_frames": hub.diagnostic_decoded_frames,
        "crc_errors": hub.parser.crc_errors,
    }
