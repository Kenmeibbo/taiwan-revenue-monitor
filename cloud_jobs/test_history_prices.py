import importlib.util
from datetime import date
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("history_prices", Path(__file__).with_name("history_prices.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MarketParsing(unittest.TestCase):
    def response(self):
        return {"stat": "ok", "date": "20260930", "tables": [{"fields": ["代號", "收盤"], "data": [[str(1100+i), "77.30"] for i in range(110)]}]}

    def test_exact_market_date_and_raw_closing_price(self):
        quotes = module.parse_market(self.response(), date(2026, 9, 30), "official")
        self.assertEqual(quotes["1100"]["price"], 77.3)
        self.assertEqual(quotes["1100"]["date"], "2026-09-30")

    def test_invalid_date_and_truncated_report_fail(self):
        with self.assertRaises(ValueError):
            module.parse_market(self.response(), date(2026, 8, 31), "official")
        body = self.response()
        body["tables"][0]["data"] = [["1100", "77.30"]]
        with self.assertRaises(ValueError):
            module.parse_market(body, date(2026, 9, 30), "official")

    def test_no_trade_markers_are_not_zero_prices(self):
        body = self.response()
        body["tables"][0]["data"] += [["9999", "--"], ["8888", "0.00"]]
        quotes = module.parse_market(body, date(2026, 9, 30), "official")
        self.assertNotIn("9999", quotes)
        self.assertNotIn("8888", quotes)


if __name__ == "__main__":
    unittest.main()

