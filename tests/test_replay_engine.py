from __future__ import annotations

import unittest
from decimal import Decimal

from bos75 import (
    Candle,
    Direction,
    ExplicitStructureSeed,
    ReplayEngine,
    ReplayStep,
    StrategyState,
    StructureLevel,
    StructureState,
)
from bos75.models import EventType


SYMBOL = "EURUSD"


def candle(index: int, high: str, low: str, close: str, open_: str | None = None) -> Candle:
    return Candle(
        symbol=SYMBOL,
        timestamp=f"t{index}",
        index=index,
        open=open_ or close,
        high=high,
        low=low,
        close=close,
    )


def seed() -> ExplicitStructureSeed:
    return ExplicitStructureSeed(
        symbol=SYMBOL,
        active_high_price="100",
        active_high_timestamp="seed_high",
        active_high_index=0,
        active_low_price="90",
        active_low_timestamp="seed_low",
        active_low_index=0,
    )


class ReplayEngineTests(unittest.TestCase):
    def test_replay_requires_explicit_structure_before_bos_evaluation(self) -> None:
        replay = ReplayEngine(SYMBOL)

        with self.assertRaises(ValueError):
            replay.feed(ReplayStep(candle=candle(1, high="101", low="95", close="99")))

    def test_seed_explicit_structure_completes_warmup_without_trade(self) -> None:
        replay = ReplayEngine(SYMBOL)

        structure = replay.seed_explicit_structure(seed())

        self.assertEqual(structure.active_high.price, Decimal("100"))
        self.assertEqual(structure.active_low.price, Decimal("90"))
        self.assertEqual(replay.strategy.state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)
        self.assertIsNone(replay.strategy.pending_setup)
        self.assertEqual(replay.logs[0].event, EventType.STRUCTURE_SEEDED.value)

    def test_seeded_replay_places_bullish_pending_setup_from_valid_bos(self) -> None:
        replay = ReplayEngine(SYMBOL)
        replay.seed_explicit_structure(seed())

        replay.feed(ReplayStep(candle=candle(1, high="96", low="92", close="95")))
        snapshot = replay.feed(
            ReplayStep(
                candle=candle(2, high="102", low="88", close="101"),
                bullish_leg_start_index=1,
            )
        )

        self.assertIsNotNone(snapshot.pending_setup)
        self.assertEqual(snapshot.pending_setup.direction, Direction.BULLISH)
        self.assertEqual(snapshot.pending_setup.entry, Decimal("91.00"))
        self.assertEqual(snapshot.pending_setup.stop_loss, Decimal("88"))
        self.assertEqual(snapshot.pending_setup.take_profit, Decimal("100"))
        self.assertEqual(snapshot.state, StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY)
        self.assertIn(
            EventType.VALID_BULLISH_BOS.value,
            [log.event for log in snapshot.logs],
        )
        self.assertIn(
            EventType.PENDING_ORDER_PLACED.value,
            [log.event for log in snapshot.logs],
        )

    def test_replay_lifecycle_marks_fill_and_target(self) -> None:
        replay = ReplayEngine(SYMBOL)
        replay.seed_explicit_structure(seed())
        replay.feed(ReplayStep(candle=candle(1, high="96", low="92", close="95")))
        replay.feed(
            ReplayStep(
                candle=candle(2, high="102", low="88", close="101"),
                bullish_leg_start_index=1,
            )
        )

        position = replay.mark_entry_filled("fill")
        replay.mark_target_hit("target")

        self.assertEqual(position.setup.direction, Direction.BULLISH)
        self.assertIsNone(replay.strategy.position)
        self.assertEqual(replay.strategy.state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)
        self.assertEqual(replay.logs[-1].event, EventType.TARGET_HIT.value)

    def test_structure_override_is_logged_and_used_for_next_bos_check(self) -> None:
        replay = ReplayEngine(SYMBOL)
        replay.seed_explicit_structure(seed())
        override = StructureState(
            symbol=SYMBOL,
            active_high=StructureLevel("ASH", "110", "manual_high", 10),
            active_low=StructureLevel("ASL", "95", "manual_low", 10),
        )

        snapshot = replay.feed(
            ReplayStep(
                candle=candle(11, high="112", low="100", close="111"),
                structure_override=override,
                bullish_leg_start_index=11,
            )
        )

        self.assertEqual(snapshot.pending_setup.take_profit, Decimal("110"))
        self.assertIn(
            EventType.STRUCTURE_UPDATED.value,
            [log.event for log in snapshot.logs],
        )

    def test_serialized_logs_convert_decimals_and_states(self) -> None:
        replay = ReplayEngine(SYMBOL)
        replay.seed_explicit_structure(seed())
        replay.feed(
            ReplayStep(
                candle=candle(1, high="102", low="88", close="101"),
                bullish_leg_start_index=1,
            )
        )

        serialized = replay.serialized_logs()

        self.assertIsInstance(serialized[0]["data"]["active_structural_high"], str)
        self.assertEqual(serialized[-1]["state_after"], StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY.value)


if __name__ == "__main__":
    unittest.main()
