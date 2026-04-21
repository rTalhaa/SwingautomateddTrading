from __future__ import annotations

from decimal import Decimal

from .models import BOSEvent, Direction, TradeSetup


class SetupGenerator:
    RETRACEMENT = Decimal("0.75")

    @classmethod
    def from_bos(cls, bos: BOSEvent) -> TradeSetup:
        if bos.direction == Direction.BULLISH:
            high_anchor = bos.broken_level_price
            low_anchor = bos.protected_extreme_price
            entry = high_anchor - cls.RETRACEMENT * (high_anchor - low_anchor)
            setup = TradeSetup(
                id=f"setup:{bos.id}",
                symbol=bos.symbol,
                direction=bos.direction,
                entry=entry,
                stop_loss=low_anchor,
                take_profit=high_anchor,
                high_anchor=high_anchor,
                low_anchor=low_anchor,
                source_bos_id=bos.id,
                created_at=bos.timestamp,
            )
        else:
            low_anchor = bos.broken_level_price
            high_anchor = bos.protected_extreme_price
            entry = low_anchor + cls.RETRACEMENT * (high_anchor - low_anchor)
            setup = TradeSetup(
                id=f"setup:{bos.id}",
                symbol=bos.symbol,
                direction=bos.direction,
                entry=entry,
                stop_loss=high_anchor,
                take_profit=low_anchor,
                high_anchor=high_anchor,
                low_anchor=low_anchor,
                source_bos_id=bos.id,
                created_at=bos.timestamp,
            )

        cls._validate_one_to_three_geometry(setup)
        return setup

    @staticmethod
    def _validate_one_to_three_geometry(setup: TradeSetup) -> None:
        if setup.risk <= 0:
            raise ValueError("setup risk must be positive")
        if setup.reward != setup.risk * Decimal("3"):
            raise ValueError("setup reward must equal 3x risk before tick rounding")
