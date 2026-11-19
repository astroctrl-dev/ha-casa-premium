"""Isolated quality/API contract smoke test. No Home Assistant or CASA connection."""
import ast
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
quality_path = root / "custom_components/casa_premium/quality.py"
spec = importlib.util.spec_from_file_location("casa_quality_isolated", quality_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
monitor = module.QualityMonitor()
assert set(module.EXPECTED_SENSORS) == {"outdoor_temp", "supply_temp", "extract_temp", "exhaust_temp"}
monitor.connection(True)
for _ in range(40):
    monitor.receive(64, 1, 0, module.EXPECTED_SENSORS)
assert monitor.snapshot()["crc"]["status"] == "unknown"
assert monitor.snapshot()["tcp"]["status"] in ("ok", "warning")
monitor.connection(False)
assert monitor.snapshot()["tcp"]["status"] == "error"
monitor.connection(True)
monitor.receive(64, 1, 0, module.EXPECTED_SENSORS)
assert monitor.epoch == 2
assert len(monitor.receive_epochs) == len(monitor.receives)
monitor.start_calibration()
try:
    monitor.commit_calibration()
except ValueError:
    pass
else:
    raise AssertionError("Premature calibration commit accepted")
monitor.reset_calibration()
assert monitor.calibration_started is None
assert monitor.baseline == module.DEFAULT_BASELINE
integration = (root / "custom_components/casa_premium/__init__.py").read_text()
app = (root / "casa_live_analysis/server.py").read_text()
for name, source in (("integration", integration), ("app", app)):
    ast.parse(source, filename=name)
for command in ("casa_premium/diagnostics", "casa_premium/quality"):
    assert command in integration and command in app, command
assert "baseline_store.async_save" in integration
assert "if a[1] == b[1]" in quality_path.read_text()
print("PASS: isolated monitor, reconnect, calibration guard, API contract, syntax")
