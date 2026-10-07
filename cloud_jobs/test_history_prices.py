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

    def test_emerging_average_uses_real_trading_day_and_is_not_labelled_close(self):
        body={"stat":"ok","tables":[{"fields":["日期","成交均價","成交均價"],"data":[["114/09/30","0","0"],["114/09/29","0","52.00"]]}]}
        quote=module.individual_quote(body,"202509","official",True)
        self.assertEqual(quote["date"],"2025-09-29")
        self.assertEqual(quote["basis"],"esb_external_average")


if __name__ == "__main__":
    unittest.main()

