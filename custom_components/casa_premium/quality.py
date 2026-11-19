"""Shared, read-only communication quality monitor for CASA Premium.

No device writes. All times are HA monotonic receive observations, not RS-485 wire timing.
"""
from collections import deque, defaultdict
from statistics import median
from time import monotonic
import json
from pathlib import Path

DEFAULT_BASELINE = {"tcp_median_ms": 150.0, "sensor_intervals_ms": {}}
EXPECTED_SENSORS = ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp",
                    "supply_fan_rpm", "extract_fan_rpm")
MIN_CRC_SAMPLES = 1000


class QualityMonitor:
    def __init__(self, baseline=None):
        self.baseline = baseline or dict(DEFAULT_BASELINE)
        self.connected = False
        self.receives = deque(maxlen=5000)
        self.valid_frames = 0
        self.crc_errors = 0
        self.sensor_updates = defaultdict(lambda: deque(maxlen=100))
        self.last_seen = {}
        self.reconnects = deque(maxlen=100)
        self.calibration_started = None
        self.calibration_receives = []
        self.calibration_sensors = defaultdict(list)
        self.calibration_crc_start = 0
        self.calibration_frames_start = 0

    def connection(self, connected):
        now = monotonic()
        if connected and not self.connected:
            self.reconnects.append(now)
        self.connected = connected

    def receive(self, byte_count, valid_frames, crc_errors, sensor_keys=()):
        now = monotonic()
        if byte_count:
            self.receives.append(now)
            if self.calibration_started is not None:
                self.calibration_receives.append(now)
        self.valid_frames += valid_frames
        self.crc_errors += crc_errors
        for key in sensor_keys:
            if key not in EXPECTED_SENSORS:
                continue
            self.sensor_updates[key].append(now)
            if self.calibration_started is not None:
                self.calibration_sensors[key].append(now)
            self.last_seen[key] = now

    def start_calibration(self):
        if self.calibration_started is not None:
            raise ValueError('Calibration already running')
        self.calibration_started = monotonic()
        self.calibration_receives = []
        self.calibration_sensors = defaultdict(list)
        self.calibration_crc_start = self.crc_errors
        self.calibration_frames_start = self.valid_frames

    def commit_calibration(self):
        if self.calibration_started is None or monotonic() - self.calibration_started < 1800:
            raise ValueError('Calibration requires 30 minutes')
        crc = self.crc_errors - self.calibration_crc_start
        valid = self.valid_frames - self.calibration_frames_start
        if valid + crc < MIN_CRC_SAMPLES or crc / (valid + crc) >= 0.001:
            raise ValueError('Insufficient or poor CRC quality')
        receive = [b-a for a,b in zip(self.calibration_receives, self.calibration_receives[1:])]
        if len(receive) < 30 or any(g > 6 for g in receive):
            raise ValueError('Insufficient or interrupted TCP traffic')
        sensor_intervals = {}
        for key in EXPECTED_SENSORS:
            times = self.calibration_sensors[key]
            if len(times) < 11:
                raise ValueError(f'Insufficient sensor observations: {key}')
            sensor_intervals[key] = round(1000 * median(b-a for a,b in zip(times,times[1:])), 1)
        candidate = {'tcp_median_ms': round(1000*median(receive),1),
                     'sensor_intervals_ms': sensor_intervals}
        self.baseline = candidate
        self.calibration_started = None
        return candidate

    def reset_calibration(self):
        self.baseline = dict(DEFAULT_BASELINE)
        self.calibration_started = None

    def snapshot(self):
        now = monotonic()
        total = self.valid_frames + self.crc_errors
        percent = round(100 * self.crc_errors / total, 3) if total else None
        crc_state = ("unknown" if total < MIN_CRC_SAMPLES else
                     "ok" if percent < 0.1 else
                     "warning" if percent <= 1 else "error")
        intervals = [b-a for a, b in zip(self.receives, list(self.receives)[1:])]
        tcp_ref = max(0.001, float(self.baseline.get("tcp_median_ms", 150)) / 1000)
        gaps = [g for g in intervals if g > max(0.5, 5*tcp_ref)]
        # Only confirmed connection transitions may be excluded from gap alarms.
        tcp_state = ("error" if not self.connected else
                     "unknown" if len(intervals) < 30 else
                     "error" if any(g > 6 for g in gaps) else
                     "warning" if gaps else "ok")
        sensors = {}
        worst = 0
        sufficient = True
        for key in EXPECTED_SENSORS:
            observations = list(self.sensor_updates[key])
            reference_ms = self.baseline.get("sensor_intervals_ms", {}).get(key)
            if reference_ms is None and len(observations) >= 4:
                reference_ms = median(b-a for a, b in zip(observations, observations[1:])) * 1000
            if not reference_ms or reference_ms <= 0 or key not in self.last_seen:
                sufficient = False
                sensors[key] = {"status": "unknown"}
                continue
            age = max(0, now - self.last_seen[key])
            factor = age * 1000 / reference_ms
            worst = max(worst, factor)
            sensors[key] = {"age_s": round(age, 1), "factor": round(factor, 2),
                            "reference_ms": round(reference_ms, 1)}
        sensor_state = ("unknown" if not sufficient else
                        "ok" if worst < 3 else "warning" if worst <= 5 else "error")
        return {
            "tcp": {"status": tcp_state, "unexpected_gaps": len(gaps),
                    "connected": self.connected},
            "crc": {"status": crc_state, "percent": percent, "checked": total,
                    "errors": self.crc_errors},
            "sensor": {"status": sensor_state,
                       "worst_factor": round(worst, 2) if sufficient else None,
                       "details": sensors},
            "baseline": self.baseline,
        }
