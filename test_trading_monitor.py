import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import trading_monitor as monitor

class MonitorTests(unittest.TestCase):
    def test_default_is_preview_only(self):
        with patch.object(monitor, "connect") as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
            self.assertEqual(monitor.deliver("morning", "2026-09-29", "test", "body", False), "preview only; no email sent")

    def test_material_threshold_and_freshness(self):
        local = datetime(2026, 9, 29, 11, 0, tzinfo=ZoneInfo("America/Toronto"))
        rows = [
            {"symbol":"A","candle_time":"2026-09-29","last_candle_close":100,"metrics":{"change_1bar_pct":5.1}},
            {"symbol":"B","candle_time":"2026-09-28","last_candle_close":100,"metrics":{"change_1bar_pct":8}},
            {"symbol":"C","candle_time":"2026-09-29","last_candle_close":100,"metrics":{"change_1bar_pct":4.9}},
        ]
        self.assertEqual([x["symbol"] for x in monitor.material_alerts(rows, local)], ["A"])

    def test_report_no_recommendation(self):
        report = monitor.format_report("morning", [], datetime(2026,9,29,9,tzinfo=ZoneInfo("America/Toronto")))
        self.assertIn("No candidates were invented", report)
        self.assertIn("No trade instructions", report)

if __name__ == "__main__":
    unittest.main()
