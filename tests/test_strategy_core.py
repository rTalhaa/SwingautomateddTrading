from __future__ import annotations

import unittest
from decimal import Decimal

from bos75 import (
    BOSDetector,
    Candle,
    Direction,
    ExpansionLeg,
    SetupGenerator,
    StrategyEngine,
    StrategyState,
    StructureLevel,
    StructureState,
)
from bos75.models import BOSEvent, EventType
from bos75.structure import StructureAmbiguityError


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


def structure() -> StructureState:
    return StructureState(
        symbol=SYMBOL,
        active_high=StructureLevel("ASH", "100", "seed_high", 0),
        active_low=StructureLevel("ASL", "90", "seed_low", 0),
    )


def bullish_bos(index: int = 3, protected: str = "88") -> BOSEvent:
    return BOSEvent(
        id=f"{SYMBOL}:bullish:{index}",
        symbol=SYMBOL,
        direction=Direction.BULLISH,
        timestamp=f"t{index}",
        candle_index=index,
        broken_level_name="ASH",
        broken_level_price=Decimal("100"),
        expansion_leg=ExpansionLeg(Direction.BULLISH, 1, index),
        protected_extreme_price=Decimal(protected),
        protected_extreme_timestamp="t2",
        protected_extreme_index=2,
    )


def bearish_bos(index: int = 4, protected: str = "104") -> BOSEvent:
    return BOSEvent(
        id=f"{SYMBOL}:bearish:{index}",
        symbol=SYMBOL,
        direction=Direction.BEARISH,
        timestamp=f"t{index}",
        candle_index=index,
        broken_level_name="ASL",
        broken_level_price=Decimal("90"),
        expansion_leg=ExpansionLeg(Direction.BEARISH, 1, index),
        protected_extreme_price=Decimal(protected),
        protected_extreme_timestamp="t2",
        protected_extreme_index=2,
    )


class BOSDetectorTests(unittest.TestCase):
    def test_wick_only_break_above_ash_is_not_bullish_bos(self) -> None:
        decision = BOSDetector().evaluate_closed_candle(
            [candle(1, high="101", low="95", close="99")],
            structure(),
        )

        self.assertIsNone(decision.event)
        self.assertEqual(decision.logs[0].event, EventType.NO_BOS.value)
        self.assertTrue(decision.logs[0].data["wick_above_ash"])

    def test_wick_only_break_below_asl_is_not_bearish_bos(self) -> None:
        decision = BOSDetector().evaluate_closed_candle(
            [candle(1, high="95", low="89", close="91")],
            structure(),
        )

        self.assertIsNone(decision.event)
        self.assertEqual(decision.logs[0].event, EventType.NO_BOS.value)
        self.assertTrue(decision.logs[0].data["wick_below_asl"])

    def test_close_above_ash_triggers_bullish_bos_with_protected_low(self) -> None:
        candles = [
            candle(1, high="96", low="92", close="95"),
            candle(2, high="99", low="88", close="98"),
            candle(3, high="102", low="97", close="101"),
        ]

        decision = BOSDetector().evaluate_closed_candle(
            candles,
            structure(),
            bullish_leg_start_index=1,
        )

        self.assertIsNotNone(decision.event)
        self.assertEqual(decision.logs[0].event, EventType.VALID_BULLISH_BOS.value)
        self.assertEqual(decision.event.direction, Direction.BULLISH)
        self.assertEqual(decision.event.broken_level_price, Decimal("100"))
        self.assertEqual(decision.event.protected_extreme_price, Decimal("88"))
        self.assertEqual(decision.event.protected_extreme_index, 2)

    def test_close_below_asl_triggers_bearish_bos_with_protected_high(self) -> None:
        candles = [
            candle(1, high="98", low="92", close="94"),
            candle(2, high="104", low="91", close="92"),
            candle(3, high="93", low="88", close="89"),
        ]

        decision = BOSDetector().evaluate_closed_candle(
            candles,
            structure(),
            bearish_leg_start_index=1,
        )

        self.assertIsNotNone(decision.event)
        self.assertEqual(decision.logs[0].event, EventType.VALID_BEARISH_BOS.value)
        self.assertEqual(decision.event.direction, Direction.BEARISH)
        self.assertEqual(decision.event.broken_level_price, Decimal("90"))
        self.assertEqual(decision.event.protected_extreme_price, Decimal("104"))
        self.assertEqual(decision.event.protected_extreme_index, 2)

    def test_bos_requires_explicit_expansion_leg_start(self) -> None:
        with self.assertRaises(StructureAmbiguityError):
            BOSDetector().evaluate_closed_candle(
                [candle(1, high="102", low="95", close="101")],
                structure(),
            )


class SetupGenerationTests(unittest.TestCase):
    def test_bullish_entry_stop_target_match_spec_formula(self) -> None:
        setup = SetupGenerator.from_bos(bullish_bos())

        self.assertEqual(setup.entry, Decimal("91.00"))
        self.assertEqual(setup.stop_loss, Decimal("88"))
        self.assertEqual(setup.take_profit, Decimal("100"))
        self.assertEqual(setup.risk, Decimal("3.00"))
        self.assertEqual(setup.reward, Decimal("9.00"))
        self.assertEqual(setup.reward, setup.risk * Decimal("3"))

    def test_bearish_entry_stop_target_match_spec_formula(self) -> None:
        setup = SetupGenerator.from_bos(bearish_bos())

        self.assertEqual(setup.entry, Decimal("100.50"))
        self.assertEqual(setup.stop_loss, Decimal("104"))
        self.assertEqual(setup.take_profit, Decimal("90"))
        self.assertEqual(setup.risk, Decimal("3.50"))
        self.assertEqual(setup.reward, Decimal("10.50"))
        self.assertEqual(setup.reward, setup.risk * Decimal("3"))


class ExecutionLifecycleTests(unittest.TestCase):
    def test_same_direction_bos_replaces_previous_pending_setup(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        first = engine.on_bos(bullish_bos(index=3, protected="88"))
        second = engine.on_bos(bullish_bos(index=4, protected="84"))

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(engine.pending_setup.id, second.id)
        self.assertEqual(engine.pending_setup.direction, Direction.BULLISH)
        self.assertEqual(engine.state, StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY)
        cancellations = [
            log for log in engine.logs if log.event == EventType.PENDING_ORDER_CANCELED.value
        ]
        self.assertEqual(len(cancellations), 1)
        self.assertEqual(cancellations[0].data["reason"], "same_direction_replacement")

    def test_opposite_bos_cancels_pending_setup_and_creates_new_valid_setup(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        bullish = engine.on_bos(bullish_bos())
        bearish = engine.on_bos(bearish_bos())

        self.assertIsNotNone(bullish)
        self.assertIsNotNone(bearish)
        self.assertEqual(engine.pending_setup.id, bearish.id)
        self.assertEqual(engine.pending_setup.direction, Direction.BEARISH)
        self.assertEqual(engine.state, StrategyState.WAITING_FOR_BEARISH_RETRACE_ENTRY)
        cancellations = [
            log for log in engine.logs if log.event == EventType.PENDING_ORDER_CANCELED.value
        ]
        self.assertEqual(cancellations[0].data["reason"], "opposite_bos_invalidation")

    def test_missed_retracement_creates_no_market_chase(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")
        setup = engine.on_bos(bullish_bos())

        engine.on_setup_missed(setup.id, "missed", "target_reached_before_entry_fill")

        self.assertIsNone(engine.pending_setup)
        self.assertIsNone(engine.position)
        self.assertEqual(engine.state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)
        self.assertEqual(engine.logs[-1].event, EventType.SETUP_MISSED.value)

    def test_only_one_active_setup_exists_per_symbol(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        engine.on_bos(bullish_bos(index=3))
        engine.on_bos(bullish_bos(index=4, protected="84"))
        engine.on_bos(bearish_bos(index=5))

        active_setups = [engine.pending_setup] if engine.pending_setup is not None else []
        self.assertEqual(len(active_setups), 1)
        self.assertEqual(active_setups[0].direction, Direction.BEARISH)

    def test_only_one_live_position_exists_per_symbol(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")
        setup = engine.on_bos(bullish_bos())
        position = engine.on_entry_filled(setup.id, "fill")

        ignored = engine.on_bos(bearish_bos())

        self.assertIsNone(ignored)
        self.assertIsNone(engine.pending_setup)
        self.assertEqual(engine.position.id, position.id)
        self.assertEqual(engine.state, StrategyState.IN_BULLISH_TRADE)
        self.assertEqual(engine.logs[-1].event, EventType.BOS_IGNORED.value)

    def test_stop_and_target_exit_return_to_waiting_for_bos(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")
        setup = engine.on_bos(bullish_bos())
        position = engine.on_entry_filled(setup.id, "fill")

        engine.on_target_hit(position.id, "target")

        self.assertIsNone(engine.position)
        self.assertEqual(engine.state, StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS)
        self.assertEqual(engine.logs[-1].event, EventType.TARGET_HIT.value)


if __name__ == "__main__":
    unittest.main()
