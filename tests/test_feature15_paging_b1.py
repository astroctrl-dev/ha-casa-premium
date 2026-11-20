"""Feature #15 B1: paging, resume, loss and deduplication cursor contract."""
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "custom_components/casa_premium/diagnostic_paging.py"
SPEC = importlib.util.spec_from_file_location("diagnostic_paging", MODULE)
paging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paging)


class DiagnosticPagingTests(unittest.TestCase):
    def test_large_buffer_is_bounded_and_resumable(self):
        events = [{"seq": i} for i in range(1, 12001)]
        cursor = 0
        seen = []
        while True:
            page = paging.diagnostic_page(events, cursor, 200, 12000)
            self.assertLessEqual(len(page["events"]), 200)
            seen.extend(event["seq"] for event in page["events"])
            cursor = page["next_after"]
            if not page["has_more"]:
                break
        self.assertEqual(seen, list(range(1, 12001)))

    def test_replayed_page_is_deduplicated_by_cursor(self):
        events = [{"seq": i} for i in range(1, 6)]
        first = paging.diagnostic_page(events, 0, 2, 5)
        second = paging.diagnostic_page(events, first["next_after"], 2, 5)
        self.assertEqual([e["seq"] for e in second["events"]], [3, 4])

    def test_overflow_reports_loss(self):
        events = [{"seq": i} for i in range(8, 13)]
        page = paging.diagnostic_page(events, 3, 2, 12)
        self.assertEqual(page["lost"], 4)
        self.assertEqual(page["next_after"], 9)
        self.assertTrue(page["has_more"])

    def test_empty_buffer_is_safe(self):
        page = paging.diagnostic_page([], 0, 200, 0)
        self.assertEqual(page["events"], [])
        self.assertFalse(page["has_more"])


if __name__ == "__main__":
    unittest.main()
