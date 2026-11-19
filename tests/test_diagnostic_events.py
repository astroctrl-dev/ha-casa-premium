"""Unit checks for bounded passive event storage (no HA runtime required)."""
import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "custom_components" / "casa_premium" / "diagnostic_events.py"
spec = importlib.util.spec_from_file_location("casa_diagnostic_events", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_empty_snapshot():
    store = module.DiagnosticEvents()
    assert store.snapshot()["events"] == []
    assert store.snapshot()["latest_seq"] == 0


def test_event_sequence_and_incremental_read():
    store = module.DiagnosticEvents()
    store.record("tcp_receive", bytes=12)
    store.record("telegram", command="0x71", bytes=20)
    snapshot = store.snapshot(after=1)
    assert [event["seq"] for event in snapshot["events"]] == [2]
    assert snapshot["events"][0]["command"] == "0x71"
    assert snapshot["events"][0]["elapsed_ms"] is not None


def test_bounded_buffer_and_loss_detection():
    store = module.DiagnosticEvents()
    for _ in range(module.MAX_EVENTS + 3):
        store.record("tcp_receive", bytes=1)
    snapshot = store.snapshot(after=1)
    assert len(snapshot["events"]) == module.MAX_EVENTS
    assert snapshot["oldest_seq"] == 4
    assert snapshot["lost"] == 2
