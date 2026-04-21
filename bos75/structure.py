from __future__ import annotations

from dataclasses import dataclass

from .models import (
    BOSEvent,
    Candle,
    Direction,
    EventType,
    ExpansionLeg,
    LogRecord,
    StructureState,
)


class StructureAmbiguityError(RuntimeError):
    """Raised when the spec requires a structure decision that is not defined."""


@dataclass(frozen=True)
class BOSDecision:
    event: BOSEvent | None
    logs: list[LogRecord]


class BOSDetector:
    """Detects close-confirmed BOS against explicitly supplied structure levels."""

    def evaluate_closed_candle(
        self,
        candles: list[Candle],
        structure: StructureState,
        *,
        bullish_leg_start_index: int | None = None,
        bearish_leg_start_index: int | None = None,
    ) -> BOSDecision:
        if not candles:
            raise ValueError("at least one closed candle is required")

        candle = candles[-1]
        if candle.symbol != structure.symbol:
            raise ValueError("candle symbol does not match structure symbol")

        base_data = {
            "candle_index": candle.index,
            "candle_timestamp": candle.timestamp,
            "candle_high": candle.high,
            "candle_low": candle.low,
            "candle_close": candle.close,
            "active_structural_high": structure.active_high.price,
            "active_structural_low": structure.active_low.price,
            "wick_above_ash": candle.high > structure.active_high.price,
            "wick_below_asl": candle.low < structure.active_low.price,
        }

        if candle.close > structure.active_high.price:
            if bullish_leg_start_index is None:
                raise StructureAmbiguityError(
                    "bullish BOS requires an explicit bullish expansion-leg start index"
                )
            event = self._build_bos_event(
                candles=candles,
                structure=structure,
                direction=Direction.BULLISH,
                leg_start_index=bullish_leg_start_index,
            )
            return BOSDecision(
                event=event,
                logs=[
                    LogRecord(
                        event=EventType.VALID_BULLISH_BOS.value,
                        symbol=candle.symbol,
                        timestamp=candle.timestamp,
                        message="Closed candle confirmed bullish BOS above ASH.",
                        data={
                            **base_data,
                            "broken_level_name": event.broken_level_name,
                            "broken_level_price": event.broken_level_price,
                            "expansion_leg_start_index": event.expansion_leg.start_index,
                            "expansion_leg_end_index": event.expansion_leg.end_index,
                            "protected_extreme_price": event.protected_extreme_price,
                            "protected_extreme_timestamp": event.protected_extreme_timestamp,
                        },
                    )
                ],
            )

        if candle.close < structure.active_low.price:
            if bearish_leg_start_index is None:
                raise StructureAmbiguityError(
                    "bearish BOS requires an explicit bearish expansion-leg start index"
                )
            event = self._build_bos_event(
                candles=candles,
                structure=structure,
                direction=Direction.BEARISH,
                leg_start_index=bearish_leg_start_index,
            )
            return BOSDecision(
                event=event,
                logs=[
                    LogRecord(
                        event=EventType.VALID_BEARISH_BOS.value,
                        symbol=candle.symbol,
                        timestamp=candle.timestamp,
                        message="Closed candle confirmed bearish BOS below ASL.",
                        data={
                            **base_data,
                            "broken_level_name": event.broken_level_name,
                            "broken_level_price": event.broken_level_price,
                            "expansion_leg_start_index": event.expansion_leg.start_index,
                            "expansion_leg_end_index": event.expansion_leg.end_index,
                            "protected_extreme_price": event.protected_extreme_price,
                            "protected_extreme_timestamp": event.protected_extreme_timestamp,
                        },
                    )
                ],
            )

        return BOSDecision(
            event=None,
            logs=[
                LogRecord(
                    event=EventType.NO_BOS.value,
                    symbol=candle.symbol,
                    timestamp=candle.timestamp,
                    message="Closed candle did not confirm BOS.",
                    data=base_data,
                )
            ],
        )

    def _build_bos_event(
        self,
        *,
        candles: list[Candle],
        structure: StructureState,
        direction: Direction,
        leg_start_index: int,
    ) -> BOSEvent:
        candle = candles[-1]
        leg = ExpansionLeg(
            direction=direction,
            start_index=leg_start_index,
            end_index=candle.index,
        )
        protected_candle = leg.protected_extreme(candles)

        if direction == Direction.BULLISH:
            broken_level = structure.active_high
            protected_price = protected_candle.low
        else:
            broken_level = structure.active_low
            protected_price = protected_candle.high

        event_id = (
            f"{structure.symbol}:{direction.value}:"
            f"{candle.index}:{broken_level.name}:{broken_level.price}"
        )
        return BOSEvent(
            id=event_id,
            symbol=structure.symbol,
            direction=direction,
            timestamp=candle.timestamp,
            candle_index=candle.index,
            broken_level_name=broken_level.name,
            broken_level_price=broken_level.price,
            expansion_leg=leg,
            protected_extreme_price=protected_price,
            protected_extreme_timestamp=protected_candle.timestamp,
            protected_extreme_index=protected_candle.index,
        )
