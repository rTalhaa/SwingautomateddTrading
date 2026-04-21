from __future__ import annotations

import os
import unittest

from bos75.cli import fetch_mt5_candles, smoke_mt5_order_check


@unittest.skipUnless(
    os.environ.get("BOS75_MT5_INTEGRATION") == "1",
    "set BOS75_MT5_INTEGRATION=1 to run original MT5 terminal smoke test",
)
class OriginalMT5IntegrationTests(unittest.TestCase):
    def test_original_terminal_order_check_smoke(self) -> None:
        result = smoke_mt5_order_check(
            os.environ.get("BOS75_MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe"),
            os.environ.get("BOS75_MT5_SYMBOL", "EURUSD"),
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["order_check_retcode"], 0)
        self.assertIn(result["symbol"], {"EURUSD", "GBPUSD", "USDJPY"})

    def test_original_terminal_closed_candle_fetch(self) -> None:
        result = fetch_mt5_candles(
            terminal_path=os.environ.get("BOS75_MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe"),
            symbol=os.environ.get("BOS75_MT5_SYMBOL", "EURUSD"),
            timeframe=os.environ.get("BOS75_MT5_TIMEFRAME", "M15"),
            count=3,
        )

        self.assertEqual(result["symbol"], os.environ.get("BOS75_MT5_SYMBOL", "EURUSD"))
        self.assertEqual(result["count"], 3)
        self.assertEqual([candle["index"] for candle in result["candles"]], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
