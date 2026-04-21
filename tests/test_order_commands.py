from __future__ import annotations

import unittest
from decimal import Decimal

from bos75 import Direction, ExpansionLeg, OrderCommandType, PendingOrderType, StrategyEngine
from bos75.models import BOSEvent, EventType


SYMBOL = "EURUSD"


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


class OrderCommandTests(unittest.TestCase):
    def test_bullish_bos_emits_buy_limit_command(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        setup = engine.on_bos(bullish_bos())

        self.assertEqual(len(engine.commands), 1)
        command = engine.commands[0]
        self.assertEqual(command.command_type, OrderCommandType.PLACE_PENDING_LIMIT)
        self.assertEqual(command.order_type, PendingOrderType.BUY_LIMIT)
        self.assertEqual(command.setup_id, setup.id)
        self.assertEqual(command.entry, setup.entry)
        self.assertEqual(command.stop_loss, setup.stop_loss)
        self.assertEqual(command.take_profit, setup.take_profit)

    def test_bearish_bos_emits_sell_limit_command(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        setup = engine.on_bos(bearish_bos())

        self.assertEqual(len(engine.commands), 1)
        command = engine.commands[0]
        self.assertEqual(command.command_type, OrderCommandType.PLACE_PENDING_LIMIT)
        self.assertEqual(command.order_type, PendingOrderType.SELL_LIMIT)
        self.assertEqual(command.direction, Direction.BEARISH)
        self.assertEqual(command.setup_id, setup.id)

    def test_replacement_emits_cancel_before_new_place_command(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")

        first = engine.on_bos(bullish_bos(index=3))
        second = engine.on_bos(bearish_bos(index=4))

        self.assertEqual([command.command_type for command in engine.commands], [
            OrderCommandType.PLACE_PENDING_LIMIT,
            OrderCommandType.CANCEL_PENDING_ORDER,
            OrderCommandType.PLACE_PENDING_LIMIT,
        ])
        self.assertEqual(engine.commands[1].setup_id, first.id)
        self.assertEqual(engine.commands[1].reason, "opposite_bos_invalidation")
        self.assertEqual(engine.commands[1].replacement_bos_id, bearish_bos(index=4).id)
        self.assertEqual(engine.commands[2].setup_id, second.id)

    def test_setup_missed_emits_cancel_command_and_setup_missed_log(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")
        setup = engine.on_bos(bullish_bos())

        engine.on_setup_missed(setup.id, "missed", "target_reached_before_entry_fill")

        self.assertEqual(engine.commands[-1].command_type, OrderCommandType.CANCEL_PENDING_ORDER)
        self.assertEqual(engine.commands[-1].setup_id, setup.id)
        self.assertEqual(engine.commands[-1].reason, "setup_missed:target_reached_before_entry_fill")
        self.assertEqual(engine.logs[-2].event, EventType.PENDING_ORDER_CANCELED.value)
        self.assertEqual(engine.logs[-1].event, EventType.SETUP_MISSED.value)

    def test_command_serialization_is_adapter_ready(self) -> None:
        engine = StrategyEngine(SYMBOL)
        engine.complete_warmup("ready")
        setup = engine.on_bos(bullish_bos())

        serialized = engine.commands[-1].to_dict()

        self.assertEqual(serialized["command_type"], "place_pending_limit")
        self.assertEqual(serialized["order_type"], "buy_limit")
        self.assertEqual(serialized["setup_id"], setup.id)
        self.assertEqual(serialized["entry"], "91.00")
        self.assertEqual(serialized["stop_loss"], "88")
        self.assertEqual(serialized["take_profit"], "100")


if __name__ == "__main__":
    unittest.main()
