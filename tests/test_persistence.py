from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bos75 import (
    Candle,
    Direction,
    ExpansionLeg,
    JsonStateStore,
    OrderCommandType,
    PendingOrderType,
    RuntimeState,
    StrategyState,
    StructureLevel,
    StructureState,
    TradeSetup,
)
from bos75.models import BOSEvent, LogRecord, Position
from bos75.orders import cancel_pending_order_from_setup, place_pending_limit_from_setup
from bos75.persistence import RuntimeState as RuntimeStateModel


SYMBOL = "EURUSD"


def structure() -> StructureState:
    return StructureState(
        symbol=SYMBOL,
        active_high=StructureLevel("ASH", "1.20000", "seed-high", 0),
        active_low=StructureLevel("ASL", "1.10000", "seed-low", 0),
    )


def setup() -> TradeSetup:
    bos = BOSEvent(
        id="bos-1",
        symbol=SYMBOL,
        direction=Direction.BULLISH,
        timestamp="t2",
        candle_index=2,
        broken_level_name="ASH",
        broken_level_price=Decimal("1.20000"),
        expansion_leg=ExpansionLeg(Direction.BULLISH, 0, 2),
        protected_extreme_price=Decimal("1.10000"),
        protected_extreme_timestamp="t0",
        protected_extreme_index=0,
    )
    return TradeSetup(
        id="setup-1",
        symbol=bos.symbol,
        direction=bos.direction,
        entry=Decimal("1.12500"),
        stop_loss=Decimal("1.10000"),
        take_profit=Decimal("1.20000"),
        high_anchor=bos.broken_level_price,
        low_anchor=bos.protected_extreme_price,
        source_bos_id=bos.id,
        created_at=bos.timestamp,
    )


class RuntimeStatePersistenceTests(unittest.TestCase):
    def test_runtime_state_round_trips_through_json(self) -> None:
        active_setup = setup()
        state = RuntimeState(
            symbol=SYMBOL,
            timeframe="M15",
            structure=structure(),
            last_processed_candle_timestamp="t2",
            next_candle_index=3,
            strategy_state=StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY,
            pending_setup=active_setup,
            position=Position(id="position-1", setup=active_setup, opened_at="fill"),
            candles=[
                Candle(SYMBOL, "t0", 0, "1.10000", "1.15000", "1.09000", "1.14000"),
                Candle(SYMBOL, "t1", 1, "1.14000", "1.21000", "1.13000", "1.20500"),
            ],
            commands=[
                place_pending_limit_from_setup(active_setup),
                cancel_pending_order_from_setup(
                    active_setup,
                    reason="same_direction_replacement",
                    timestamp="t3",
                    replacement_bos_id="bos-2",
                ),
            ],
            logs=[
                LogRecord(
                    event="pending_order_placed",
                    symbol=SYMBOL,
                    timestamp="t2",
                    message="placed",
                    state_before=StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS,
                    state_after=StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY,
                    data={"entry": Decimal("1.12500")},
                )
            ],
        )

        loaded = RuntimeStateModel.from_dict(json.loads(json.dumps(state.to_dict())))

        self.assertEqual(loaded.symbol, SYMBOL)
        self.assertEqual(loaded.timeframe, "M15")
        self.assertEqual(loaded.structure.active_high.price, Decimal("1.20000"))
        self.assertEqual(loaded.last_processed_candle_timestamp, "t2")
        self.assertEqual(loaded.next_candle_index, 3)
        self.assertEqual(loaded.strategy_state, StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY)
        self.assertEqual(loaded.pending_setup.entry, Decimal("1.12500"))
        self.assertEqual(loaded.position.id, "position-1")
        self.assertEqual(len(loaded.candles), 2)
        self.assertEqual(loaded.commands[0].command_type, OrderCommandType.PLACE_PENDING_LIMIT)
        self.assertEqual(loaded.commands[0].order_type, PendingOrderType.BUY_LIMIT)
        self.assertEqual(loaded.commands[1].command_type, OrderCommandType.CANCEL_PENDING_ORDER)
        self.assertEqual(loaded.logs[0].state_after, StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY)

    def test_json_state_store_returns_none_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonStateStore(Path(tmpdir) / "state.json")

            self.assertIsNone(store.load())

    def test_json_state_store_saves_and_loads_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "nested" / "state.json"
            store = JsonStateStore(state_path)
            state = RuntimeState(
                symbol=SYMBOL,
                timeframe="M15",
                structure=structure(),
                strategy_state=StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS,
            )

            store.save(state)
            loaded = store.load()

            self.assertTrue(state_path.exists())
            self.assertEqual(loaded.symbol, SYMBOL)
            self.assertEqual(loaded.strategy_state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)

    def test_runtime_state_rejects_unknown_schema_version(self) -> None:
        payload = RuntimeState(symbol=SYMBOL, timeframe="M15", structure=structure()).to_dict()
        payload["schema_version"] = 999

        with self.assertRaises(ValueError):
            RuntimeState.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
