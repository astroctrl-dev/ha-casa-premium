"""Shared, read-only communication quality monitor for CASA Premium.

No device writes. All times are HA monotonic receive observations, not RS-485 wire timing.
"""
from collections import deque, defaultdict
from statistics import median
from time import monotonic
from datetime import datetime, timezone

DEFAULT_BASELINE = {"tcp_median_ms": 150.0, "sensor_intervals_ms": {}}
EXPECTED_SENSORS = ("outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp")
MIN_CRC_SAMPLES = 1000


class QualityMonitor:
    def __init__(self, baseline=None):
        self.baseline = baseline if baseline is not None else {'tcp_median_ms': 150.0, 'sensor_intervals_ms': {}}
        self.connected = False
        self.receives = deque(maxlen=5000)
        self.valid_frames = 0
        self.crc_errors = 0
        self.sensor_updates = defaultdict(lambda: deque(maxlen=100))
        self.last_seen = {}
        self.reconnects = deque(maxlen=100)
        self.connection_epochs = deque(maxlen=100)
        self.epoch = 0
        self.receive_epochs = deque(maxlen=5000)
        self.calibration_started = None
        self.calibrated_at = None
        self.calibration_started_at = None
        self.calibration_status = 'default'
        self.calibration_receives = []
        self.calibration_sensors = defaultdict(list)
        self.calibration_crc_start = 0
        self.calibration_frames_start = 0

    def connection(self, connected):
        now = monotonic()
        if connected and not self.connected:
            self.epoch += 1
            self.reconnects.append(now)
            self.connection_epochs.append(self.epoch)
        self.connected = connected

    def receive(self, byte_count, valid_frames, crc_errors, sensor_keys=()):
        now = monotonic()
        if byte_count:
            self.receives.append(now)
            self.receive_epochs.append(self.epoch)
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
        self.calibration_started_at = datetime.now(timezone.utc).isoformat()
        self.calibration_status = 'running'
        self.calibration_receives = []
        self.calibration_sensors = defaultdict(list)
        self.calibration_crc_start = self.crc_errors
        self.calibration_frames_start = self.valid_frames

    def commit_calibration(self):
        if self.calibration_started is None:
            raise ValueError('Calibration not running')
        if monotonic() - self.calibration_started < 1800:
            raise ValueError('Calibration requires 30 minutes')
        crc = self.crc_errors - self.calibration_crc_start
        valid = self.valid_frames - self.calibration_frames_start
        if valid + crc < MIN_CRC_SAMPLES or crc / (valid + crc) >= 0.001:
            self._reject_calibration('Insufficient or poor CRC quality')
        receive = [b-a for a,b in zip(self.calibration_receives, self.calibration_receives[1:])]
        if len(receive) < 30 or any(g > 6 for g in receive):
            self._reject_calibration('Insufficient or interrupted TCP traffic')
        sensor_intervals = {}
        for key in EXPECTED_SENSORS:
            times = self.calibration_sensors[key]
            if len(times) < 11:
                self._reject_calibration(f'Insufficient sensor observations: {key}')
            sensor_intervals[key] = round(1000 * median(b-a for a,b in zip(times,times[1:])), 1)
        candidate = {'tcp_median_ms': round(1000*median(receive),1),
                     'sensor_intervals_ms': sensor_intervals}
        self.baseline = candidate
        self.calibrated_at = datetime.now(timezone.utc).isoformat()
        self.calibration_started_at = None
        self.calibration_status = 'completed'
        self.calibration_started = None
        return candidate

    def _reject_calibration(self, reason):
        """Reject a completed run without discarding the last valid baseline."""
        self.calibration_started = None
        self.calibration_started_at = None
        self.calibration_status = 'failed'
        self.calibration_receives = []
        self.calibration_sensors.clear()
        raise ValueError(reason)

    def cancel_calibration(self):
        if self.calibration_started is None:
            raise ValueError('Calibration not running')
        self.calibration_started = None
        self.calibration_started_at = None
        self.calibration_status = 'cancelled'
        self.calibration_receives = []
        self.calibration_sensors.clear()

    def reset_calibration(self):
        self.baseline = {'tcp_median_ms': 150.0, 'sensor_intervals_ms': {}}
        self.calibrated_at = None
        self.calibration_started_at = None
        self.calibration_status = 'default'
        self.calibration_started = None

    def snapshot(self):
        now = monotonic()
        remaining_seconds = max(0, int(1800 - (now - self.calibration_started) + 0.999)) if self.calibration_started is not None else 0
        total = self.valid_frames + self.crc_errors
        percent = round(100 * self.crc_errors / total, 3) if total else None
        crc_state = ("unknown" if total < MIN_CRC_SAMPLES else
                     "ok" if percent < 0.1 else
                     "warning" if percent <= 1 else "error")
        observations = list(zip(self.receives, self.receive_epochs))
        intervals = [b[0]-a[0] for a,b in zip(observations, observations[1:])
                     if a[1] == b[1]]
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
        # Functional quality is independent of historical TCP read pauses.
        # An active disconnect, missing sensor, or insufficient CRC evidence
        # must never be presented as a healthy overall result.
        if not self.connected:
            overall_state = 'error'
            overall_reason = 'tcp_disconnected'
        elif sensor_state == 'error' or crc_state == 'error':
            overall_state = 'error'
            overall_reason = 'sensor_or_crc_error'
        elif sensor_state == 'unknown' or crc_state == 'unknown':
            overall_state = 'unknown'
            overall_reason = 'insufficient_evidence'
        elif sensor_state == 'warning' or crc_state == 'warning':
            overall_state = 'warning'
            overall_reason = 'sensor_or_crc_warning'
        else:
            overall_state = 'ok'
            overall_reason = 'sensors_and_crc_ok'
        return {
            'overall': {'status': overall_state, 'reason': overall_reason},
            "tcp": {"status": tcp_state, "unexpected_gaps": len(gaps),
                    "connected": self.connected},
            "crc": {"status": crc_state, "percent": percent, "checked": total,
                    "errors": self.crc_errors},
            "sensor": {"status": sensor_state,
                       "worst_factor": round(worst, 2) if sufficient else None,
                       "details": sensors},
            "baseline": self.baseline,
            "calibration": {"status": self.calibration_status,
                            "calibrated_at": self.calibrated_at,
                            "started_at": self.calibration_started_at},
        }
