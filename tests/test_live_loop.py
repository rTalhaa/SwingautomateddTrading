from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bos75 import (
    Candle,
    Direction,
    DryRunLiveConfig,
    DryRunLiveLoop,
    ExplicitStructureSeed,
    JsonStateStore,
    MT5ExecutionResult,
    OrderCommandType,
    StrategyState,
)
from bos75.mt5_market_data import MT5CandleBatch


SYMBOL = "EURUSD"


class FakeMarketData:
    def __init__(self, batches: list[MT5CandleBatch]) -> None:
        self.batches = batches
        self.connect_count = 0
        self.shutdown_count = 0
        self.fetch_calls = []

    def connect(self) -> None:
        self.connect_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def fetch_closed_candles(self, symbol: str, timeframe: str, count: int):
        self.fetch_calls.append((symbol, timeframe, count))
        if len(self.fetch_calls) <= len(self.batches):
            return self.batches[len(self.fetch_calls) - 1]
        return self.batches[-1]


class FakeOrderAdapter:
    def __init__(self) -> None:
        self.connect_count = 0
        self.shutdown_count = 0
        self.checked_commands = []

    def connect(self) -> None:
        self.connect_count += 1

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def check_pending_limit(self, command):
        self.checked_commands.append(command)
        return MT5ExecutionResult(
            command_id=command.id,
            command_type=command.command_type,
            ok=True,
            retcode=0,
            request={"symbol": command.symbol, "price": float(command.entry)},
            message="Done",
        )


def seed() -> ExplicitStructureSeed:
    return ExplicitStructureSeed(
        symbol=SYMBOL,
        active_high_price="1.20000",
        active_high_timestamp="seed-high",
        active_high_index=0,
        active_low_price="1.10000",
        active_low_timestamp="seed-low",
        active_low_index=0,
    )


def batch(*candles: Candle) -> MT5CandleBatch:
    return MT5CandleBatch(symbol=SYMBOL, timeframe="M15", candles=list(candles))


def candle(timestamp: str, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        symbol=SYMBOL,
        timestamp=timestamp,
        index=-1,
        open=open_,
        high=high,
        low=low,
        close=close,
    )


class DryRunLiveLoopTests(unittest.TestCase):
    def test_first_run_requires_explicit_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            loop = DryRunLiveLoop(
                DryRunLiveConfig(
                    symbol=SYMBOL,
                    timeframe="M15",
                    state_path=Path(tmpdir) / "state.json",
                ),
                market_data=FakeMarketData([batch()]),
            )

            with self.assertRaises(ValueError):
                loop.run_once()

    def test_first_run_processes_new_closed_candles_and_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            market = FakeMarketData(
                [
                    batch(
                        candle("t0", "1.12000", "1.15000", "1.11000", "1.14000"),
                        candle("t1", "1.14000", "1.16000", "1.13000", "1.15000"),
                    )
                ]
            )
            loop = DryRunLiveLoop(
                DryRunLiveConfig(
                    symbol=SYMBOL,
                    timeframe="M15",
                    state_path=state_path,
                    lookback=2,
                    seed=seed(),
                ),
                market_data=market,
            )

            result = loop.run_once()
            loaded = JsonStateStore(state_path).load()

            self.assertEqual(result.processed_count, 2)
            self.assertEqual(result.skipped_count, 0)
            self.assertEqual(result.last_processed_candle_timestamp, "t1")
            self.assertEqual(result.next_candle_index, 2)
            self.assertEqual(result.new_commands, [])
            self.assertEqual(loaded.last_processed_candle_timestamp, "t1")
            self.assertEqual(loaded.next_candle_index, 2)
            self.assertEqual(loaded.strategy_state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)
            self.assertEqual([candle.index for candle in loaded.candles], [0, 1])
            self.assertEqual(market.connect_count, 1)
            self.assertEqual(market.shutdown_count, 1)

    def test_repeated_run_does_not_reprocess_same_closed_candles(self) -> None:
        candles = batch(
            candle("t0", "1.12000", "1.15000", "1.11000", "1.14000"),
            candle("t1", "1.14000", "1.16000", "1.13000", "1.15000"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            market = FakeMarketData([candles, candles])
            config = DryRunLiveConfig(
                symbol=SYMBOL,
                timeframe="M15",
                state_path=state_path,
                lookback=2,
                seed=seed(),
            )

            first = DryRunLiveLoop(config, market_data=market).run_once()
            second = DryRunLiveLoop(config, market_data=market).run_once()

            self.assertEqual(first.processed_count, 2)
            self.assertEqual(second.processed_count, 0)
            self.assertEqual(second.skipped_count, 2)
            self.assertEqual(second.next_candle_index, 2)
            self.assertEqual(JsonStateStore(state_path).load().next_candle_index, 2)

    def test_bos_run_emits_command_and_persists_pending_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            market = FakeMarketData(
                [
                    batch(
                        candle("t0", "1.12000", "1.15000", "1.09000", "1.14000"),
                        candle("t1", "1.19000", "1.21000", "1.18000", "1.20500"),
                    )
                ]
            )
            loop = DryRunLiveLoop(
                DryRunLiveConfig(
                    symbol=SYMBOL,
                    timeframe="M15",
                    state_path=state_path,
                    lookback=2,
                    seed=seed(),
                    bullish_leg_start_index=0,
                ),
                market_data=market,
            )

            result = loop.run_once()
            loaded = JsonStateStore(state_path).load()

            self.assertEqual(result.processed_count, 2)
            self.assertEqual(len(result.new_commands), 1)
            self.assertEqual(result.new_commands[0].command_type, OrderCommandType.PLACE_PENDING_LIMIT)
            self.assertEqual(loaded.pending_setup.direction, Direction.BULLISH)
            self.assertEqual(loaded.pending_setup.entry, Decimal("1.1175000"))
            self.assertEqual(loaded.strategy_state, StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY)
            self.assertEqual(loaded.last_processed_candle_timestamp, "t1")
            self.assertEqual(result.order_checks, [])

    def test_check_orders_validates_new_pending_limit_commands_without_sending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            market = FakeMarketData(
                [
                    batch(
                        candle("t0", "1.12000", "1.15000", "1.09000", "1.14000"),
                        candle("t1", "1.19000", "1.21000", "1.18000", "1.20500"),
                    )
                ]
            )
            order_adapter = FakeOrderAdapter()
            loop = DryRunLiveLoop(
                DryRunLiveConfig(
                    symbol=SYMBOL,
                    timeframe="M15",
                    state_path=Path(tmpdir) / "state.json",
                    lookback=2,
                    seed=seed(),
                    bullish_leg_start_index=0,
                    check_orders=True,
                ),
                market_data=market,
                order_adapter=order_adapter,
            )

            result = loop.run_once()
            serialized = result.to_dict()

            self.assertEqual(len(result.new_commands), 1)
            self.assertEqual(len(order_adapter.checked_commands), 1)
            self.assertEqual(order_adapter.checked_commands[0].id, result.new_commands[0].id)
            self.assertEqual(order_adapter.connect_count, 1)
            self.assertEqual(order_adapter.shutdown_count, 1)
            self.assertEqual(serialized["order_checks"][0]["checked"], True)
            self.assertEqual(serialized["order_checks"][0]["ok"], True)
            self.assertEqual(serialized["order_checks"][0]["retcode"], 0)
            self.assertEqual(serialized["order_checks"][0]["message"], "Done")

    def test_check_orders_reports_cancel_commands_as_skipped_without_sending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            market = FakeMarketData(
                [
                    batch(
                        candle("t0", "1.12000", "1.15000", "1.09000", "1.14000"),
                        candle("t1", "1.19000", "1.21000", "1.18000", "1.20500"),
                        candle("t2", "1.20500", "1.21500", "1.08000", "1.09500"),
                    )
                ]
            )
            order_adapter = FakeOrderAdapter()
            loop = DryRunLiveLoop(
                DryRunLiveConfig(
                    symbol=SYMBOL,
                    timeframe="M15",
                    state_path=Path(tmpdir) / "state.json",
                    lookback=3,
                    seed=seed(),
                    bullish_leg_start_index=0,
                    bearish_leg_start_index=0,
                    check_orders=True,
                ),
                market_data=market,
                order_adapter=order_adapter,
            )

            result = loop.run_once()
            serialized_checks = result.to_dict()["order_checks"]

            self.assertEqual(
                [command.command_type for command in result.new_commands],
                [
                    OrderCommandType.PLACE_PENDING_LIMIT,
                    OrderCommandType.CANCEL_PENDING_ORDER,
                    OrderCommandType.PLACE_PENDING_LIMIT,
                ],
            )
            self.assertEqual(len(order_adapter.checked_commands), 2)
            self.assertEqual([check["checked"] for check in serialized_checks], [True, False, True])
            self.assertIsNone(serialized_checks[1]["ok"])
            self.assertIn("cancellation was not sent", serialized_checks[1]["message"])


if __name__ == "__main__":
    unittest.main()
