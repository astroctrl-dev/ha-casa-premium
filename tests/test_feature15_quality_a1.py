"""Feature #15 A1: isolated quality monitor regression tests (no HA required)."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("casa_quality", ROOT / "custom_components/casa_premium/quality.py")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


class QualityA1Tests(unittest.TestCase):
    def healthy_monitor(self):
        m = quality.QualityMonitor(baseline={'tcp_median_ms': 150.0, 'sensor_intervals_ms': {key: 1000.0 for key in quality.EXPECTED_SENSORS}})
        m.connection(True)
        for _ in range(1000):
            m.receive(8, 1, 0, quality.EXPECTED_SENSORS)
        return m

    def test_healthy_sensors_and_crc_are_ok(self):
        m = self.healthy_monitor()
        self.assertEqual(m.snapshot()["overall"]["status"], "ok")

    def test_missing_expected_sensor_never_looks_healthy(self):
        m = quality.QualityMonitor()
        m.connection(True)
        for _ in range(1000):
            m.receive(8, 1, 0, ("outdoor_temp",))
        self.assertEqual(m.snapshot()["overall"]["status"], "unknown")

    def test_disconnect_is_error(self):
        m = self.healthy_monitor()
        m.connection(False)
        self.assertEqual(m.snapshot()["overall"]["reason"], "tcp_disconnected")

    def test_failed_calibration_preserves_baseline_and_allows_retry(self):
        baseline = {"tcp_median_ms": 128.6, "sensor_intervals_ms": {"outdoor_temp": 1000}}
        m = quality.QualityMonitor(baseline=baseline)
        m.start_calibration()
        m.calibration_started -= 1801
        with self.assertRaisesRegex(ValueError, "CRC"):
            m.commit_calibration()
        self.assertEqual(m.baseline, baseline)
        self.assertEqual(m.calibration_status, "failed")
        self.assertIsNone(m.calibration_started)
        m.start_calibration()
        self.assertEqual(m.calibration_status, "running")

    def test_cancel_keeps_baseline_and_allows_restart(self):
        m = quality.QualityMonitor(baseline={'tcp_median_ms': 128.6, 'sensor_intervals_ms': {}})
        m.start_calibration()
        self.assertGreater(m.snapshot()['calibration']['remaining_seconds'], 0)
        m.cancel_calibration()
        self.assertEqual(m.calibration_status, 'cancelled')
        self.assertEqual(m.baseline['tcp_median_ms'], 128.6)
        self.assertEqual(m.snapshot()['calibration']['remaining_seconds'], 0)
        m.start_calibration()
        self.assertEqual(m.calibration_status, 'running')

    def test_reset_uses_fresh_default_baseline(self):
        m = self.healthy_monitor()
        m.reset_calibration()
        self.assertEqual(m.calibration_status, "default")
        m.baseline["sensor_intervals_ms"]["x"] = 1
        self.assertEqual(quality.DEFAULT_BASELINE["sensor_intervals_ms"], {})


if __name__ == "__main__":
    unittest.main()
