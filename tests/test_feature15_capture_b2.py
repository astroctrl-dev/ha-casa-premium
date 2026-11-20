"""Feature 15 B2 backend capture regression tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("capture", Path(__file__).resolve().parents[1] / "casa_live_analysis/capture.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class CaptureTests(unittest.TestCase):
    def test_start_append_stop_and_saved_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            c = module.Capture(directory)
            c.start()
            self.assertEqual(c.snapshot()["status"], "running")
            c.append({"utc": "2026-11-20T12:00:00Z", "seq": 1, "kind": "tcp_receive"})
            c.stop()
            self.assertEqual(c.snapshot()["status"], "saved")
            self.assertTrue(c.file.is_file())
            self.assertIn("tcp_receive", c.file.read_text())

    def test_auto_stop_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            c = module.Capture(directory)
            c.start()
            c.deadline -= 901
            self.assertEqual(c.snapshot()["status"], "saved")

    def test_restart_exposes_saved_file(self):
        with tempfile.TemporaryDirectory() as directory:
            c = module.Capture(directory)
            c.start()
            c.stop()
            self.assertTrue(module.Capture(directory).snapshot()["file_exists"])

    def test_cannot_start_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            c = module.Capture(directory)
            c.start()
            with self.assertRaises(ValueError):
                c.start()
            c.stop()


if __name__ == "__main__":
    unittest.main()
