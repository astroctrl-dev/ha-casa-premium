import unittest
from analysis import analyze

class TestAnalysis(unittest.TestCase):
    def test_gaps_crc_and_counts(self):
        events=[
            {"kind":"tcp_receive","utc":"2026-11-19T15:00:00+00:00","bytes":32},
            {"kind":"telegram","utc":"2026-11-19T15:00:00+00:00","command":"0x73"},
            {"kind":"tcp_receive","utc":"2026-11-19T15:00:01+00:00","bytes":12},
            {"kind":"crc_error","utc":"2026-11-19T15:00:01+00:00","count":2},
            {"kind":"sensor_observation","utc":"2026-11-19T15:00:01+00:00","keys":["temperature"]},
        ]
        result=analyze(events)
        self.assertEqual(result["gaps_over_threshold"],1)
        self.assertEqual(result["tcp_bytes"],44)
        self.assertEqual(result["crc_errors"],2)
        self.assertEqual(result["telegram_commands"]["0x73"],1)
        self.assertEqual(result["sensor_keys"]["temperature"],1)

    def test_empty(self):
        self.assertEqual(analyze([])["gaps_over_threshold"],0)
        self.assertIsNone(analyze([])["tcp_interval_max_ms"])

if __name__=="__main__":
    unittest.main()
