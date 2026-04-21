from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


def price(value: Decimal | int | float | str) -> Decimal:
    """Convert price-like input without accepting binary float artifacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class StrategyState(str, Enum):
    WARMUP = "WARMUP"
    WAITING_FOR_BULLISH_OR_BEARISH_BOS = "WAITING_FOR_BULLISH_OR_BEARISH_BOS"
    WAITING_FOR_BULLISH_RETRACE_ENTRY = "WAITING_FOR_BULLISH_RETRACE_ENTRY"
    WAITING_FOR_BEARISH_RETRACE_ENTRY = "WAITING_FOR_BEARISH_RETRACE_ENTRY"
    IN_BULLISH_TRADE = "IN_BULLISH_TRADE"
    IN_BEARISH_TRADE = "IN_BEARISH_TRADE"


class EventType(str, Enum):
    NO_BOS = "no_bos"
    VALID_BULLISH_BOS = "valid_bullish_bos"
    VALID_BEARISH_BOS = "valid_bearish_bos"
    PENDING_ORDER_PLACED = "pending_order_placed"
    PENDING_ORDER_CANCELED = "pending_order_canceled"
    BULLISH_ENTRY_FILLED = "bullish_entry_filled"
    BEARISH_ENTRY_FILLED = "bearish_entry_filled"
    STOP_HIT = "stop_hit"
    TARGET_HIT = "target_hit"
    SETUP_MISSED = "setup_missed"
    BOS_IGNORED = "bos_ignored"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: Any
    index: int
    open: Decimal | int | float | str
    high: Decimal | int | float | str
    low: Decimal | int | float | str
    close: Decimal | int | float | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "open", price(self.open))
        object.__setattr__(self, "high", price(self.high))
        object.__setattr__(self, "low", price(self.low))
        object.__setattr__(self, "close", price(self.close))
        if self.high < self.low:
            raise ValueError("candle high cannot be lower than candle low")


@dataclass(frozen=True)
class StructureLevel:
    name: str
    price: Decimal | int | float | str
    timestamp: Any
    candle_index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", price(self.price))


@dataclass(frozen=True)
class StructureState:
    symbol: str
    active_high: StructureLevel
    active_low: StructureLevel

    def __post_init__(self) -> None:
        if self.active_high.price <= self.active_low.price:
            raise ValueError("active structural high must be above active structural low")


@dataclass(frozen=True)
class ExpansionLeg:
    direction: Direction
    start_index: int
    end_index: int

    def candles(self, all_candles: list[Candle]) -> list[Candle]:
        positions = {candle.index: position for position, candle in enumerate(all_candles)}
        if self.start_index not in positions:
            raise ValueError(f"expansion leg start index {self.start_index} is not in candles")
        if self.end_index not in positions:
            raise ValueError(f"expansion leg end index {self.end_index} is not in candles")

        start_position = positions[self.start_index]
        end_position = positions[self.end_index]
        if start_position > end_position:
            raise ValueError("expansion leg start must be before or equal to end")
        return all_candles[start_position : end_position + 1]

    def protected_extreme(self, all_candles: list[Candle]) -> Candle:
        leg_candles = self.candles(all_candles)
        if self.direction == Direction.BULLISH:
            return min(leg_candles, key=lambda candle: (candle.low, candle.index))
        return max(leg_candles, key=lambda candle: (candle.high, -candle.index))


@dataclass(frozen=True)
class BOSEvent:
    id: str
    symbol: str
    direction: Direction
    timestamp: Any
    candle_index: int
    broken_level_name: str
    broken_level_price: Decimal
    expansion_leg: ExpansionLeg
    protected_extreme_price: Decimal
    protected_extreme_timestamp: Any
    protected_extreme_index: int


@dataclass(frozen=True)
class TradeSetup:
    id: str
    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    high_anchor: Decimal
    low_anchor: Decimal
    source_bos_id: str
    created_at: Any

    @property
    def risk(self) -> Decimal:
        if self.direction == Direction.BULLISH:
            return self.entry - self.stop_loss
        return self.stop_loss - self.entry

    @property
    def reward(self) -> Decimal:
        if self.direction == Direction.BULLISH:
            return self.take_profit - self.entry
        return self.entry - self.take_profit


@dataclass(frozen=True)
class Position:
    id: str
    setup: TradeSetup
    opened_at: Any


@dataclass
class LogRecord:
    event: str
    symbol: str
    timestamp: Any | None
    message: str
    state_before: StrategyState | None = None
    state_after: StrategyState | None = None
    data: dict[str, Any] = field(default_factory=dict)
