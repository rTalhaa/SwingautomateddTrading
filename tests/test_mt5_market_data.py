from __future__ import annotations

import unittest
from types import SimpleNamespace

from bos75 import MT5AdapterConfig, MT5MarketDataAdapter
from bos75.mt5_adapter import MT5AdapterError
from bos75.mt5_market_data import normalize_timeframe, rates_to_candles, timeframe_to_mt5


class FakeMT5MarketData:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388

    def __init__(self) -> None:
        self.initialized_with = None
        self.shutdown_called = False
        self.selected_symbols = []
        self.copy_rates_calls = []
        self.visible = True
        self.rates = [
            {"time": 1776801000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
            {"time": 1776800100, "open": 1.0, "high": 1.15, "low": 0.95, "close": 1.1},
        ]

    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        return True

    def shutdown(self):
        self.shutdown_called = True

    def last_error(self):
        return (1, "fake error")

    def symbol_info(self, symbol):
        return SimpleNamespace(name=symbol, visible=self.visible, digits=5)

    def symbol_select(self, symbol, selected):
        self.selected_symbols.append((symbol, selected))
        self.visible = True
        return True

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.copy_rates_calls.append((symbol, timeframe, start_pos, count))
        return self.rates[:count]


class MT5MarketDataTests(unittest.TestCase):
    def test_normalize_timeframe_accepts_common_values(self) -> None:
        self.assertEqual(normalize_timeframe("m15"), "M15")
        self.assertEqual(normalize_timeframe(" H1 "), "H1")

    def test_normalize_timeframe_rejects_unknown_values(self) -> None:
        with self.assertRaises(ValueError):
            normalize_timeframe("M7")

    def test_timeframe_to_mt5_uses_client_constant(self) -> None:
        self.assertEqual(timeframe_to_mt5(FakeMT5MarketData(), "M15"), 15)

    def test_timeframe_to_mt5_raises_for_missing_constant(self) -> None:
        fake = FakeMT5MarketData()
        delattr(FakeMT5MarketData, "TIMEFRAME_H4")
        try:
            with self.assertRaises(MT5AdapterError):
                timeframe_to_mt5(fake, "H4")
        finally:
            FakeMT5MarketData.TIMEFRAME_H4 = 16388

    def test_rates_to_candles_sorts_by_time_and_assigns_indexes(self) -> None:
        candles = rates_to_candles(
            "EURUSD",
            [
                {"time": 200, "open": 2, "high": 3, "low": 1, "close": 2.5},
                {"time": 100, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            ],
            start_index=10,
        )

        self.assertEqual([candle.index for candle in candles], [10, 11])
        self.assertEqual([candle.timestamp for candle in candles], [
            "1970-01-01T00:01:40Z",
            "1970-01-01T00:03:20Z",
        ])
        self.assertEqual(str(candles[0].close), "1.5")

    def test_rates_to_candles_can_format_prices_to_symbol_digits(self) -> None:
        candles = rates_to_candles(
            "EURUSD",
            [{"time": 100, "open": 1.1, "high": 1.23456789, "low": 1.0, "close": 1.1740599999999999}],
            digits=5,
        )

        self.assertEqual(str(candles[0].open), "1.10000")
        self.assertEqual(str(candles[0].high), "1.23457")
        self.assertEqual(str(candles[0].close), "1.17406")

    def test_fetch_closed_candles_skips_current_bar(self) -> None:
        fake = FakeMT5MarketData()
        adapter = MT5MarketDataAdapter(MT5AdapterConfig(terminal_path="terminal"), mt5_client=fake)

        adapter.connect()
        batch = adapter.fetch_closed_candles("EURUSD", "M15", 2, start_index=5)
        adapter.shutdown()

        self.assertEqual(fake.initialized_with["path"], "terminal")
        self.assertEqual(fake.copy_rates_calls, [("EURUSD", 15, 1, 2)])
        self.assertTrue(fake.shutdown_called)
        self.assertEqual(batch.symbol, "EURUSD")
        self.assertEqual(batch.timeframe, "M15")
        self.assertEqual([candle.index for candle in batch.candles], [5, 6])

    def test_fetch_closed_candles_selects_hidden_symbol(self) -> None:
        fake = FakeMT5MarketData()
        fake.visible = False
        adapter = MT5MarketDataAdapter(mt5_client=fake)

        adapter.connect()
        adapter.fetch_closed_candles("EURUSD", "M1", 1)

        self.assertEqual(fake.selected_symbols, [("EURUSD", True)])

    def test_batch_serializes_candles_for_json(self) -> None:
        fake = FakeMT5MarketData()
        adapter = MT5MarketDataAdapter(mt5_client=fake)

        adapter.connect()
        payload = adapter.fetch_closed_candles("EURUSD", "M15", 1).to_dict()

        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["candles"][0]["open"], "1.10000")


if __name__ == "__main__":
    unittest.main()
