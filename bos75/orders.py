from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from .models import Direction, TradeSetup


class OrderCommandType(str, Enum):
    PLACE_PENDING_LIMIT = "place_pending_limit"
    CANCEL_PENDING_ORDER = "cancel_pending_order"


class PendingOrderType(str, Enum):
    BUY_LIMIT = "buy_limit"
    SELL_LIMIT = "sell_limit"


@dataclass(frozen=True)
class PlacePendingLimitCommand:
    id: str
    symbol: str
    order_type: PendingOrderType
    setup_id: str
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    source_bos_id: str
    timestamp: Any

    @property
    def command_type(self) -> OrderCommandType:
        return OrderCommandType.PLACE_PENDING_LIMIT

    @property
    def direction(self) -> Direction:
        if self.order_type == PendingOrderType.BUY_LIMIT:
            return Direction.BULLISH
        return Direction.BEARISH

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command_type": self.command_type.value,
            "symbol": self.symbol,
            "order_type": self.order_type.value,
            "setup_id": self.setup_id,
            "direction": self.direction.value,
            "entry": str(self.entry),
            "stop_loss": str(self.stop_loss),
            "take_profit": str(self.take_profit),
            "source_bos_id": self.source_bos_id,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CancelPendingOrderCommand:
    id: str
    symbol: str
    setup_id: str
    reason: str
    timestamp: Any
    replacement_bos_id: str | None = None

    @property
    def command_type(self) -> OrderCommandType:
        return OrderCommandType.CANCEL_PENDING_ORDER

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command_type": self.command_type.value,
            "symbol": self.symbol,
            "setup_id": self.setup_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "replacement_bos_id": self.replacement_bos_id,
        }


ExecutionCommand = PlacePendingLimitCommand | CancelPendingOrderCommand


def place_pending_limit_from_setup(setup: TradeSetup) -> PlacePendingLimitCommand:
    order_type = (
        PendingOrderType.BUY_LIMIT
        if setup.direction == Direction.BULLISH
        else PendingOrderType.SELL_LIMIT
    )
    return PlacePendingLimitCommand(
        id=f"cmd:place:{setup.id}",
        symbol=setup.symbol,
        order_type=order_type,
        setup_id=setup.id,
        entry=setup.entry,
        stop_loss=setup.stop_loss,
        take_profit=setup.take_profit,
        source_bos_id=setup.source_bos_id,
        timestamp=setup.created_at,
    )


def cancel_pending_order_from_setup(
    setup: TradeSetup,
    *,
    reason: str,
    timestamp: Any,
    replacement_bos_id: str | None = None,
) -> CancelPendingOrderCommand:
    return CancelPendingOrderCommand(
        id=f"cmd:cancel:{setup.id}:{reason}",
        symbol=setup.symbol,
        setup_id=setup.id,
        reason=reason,
        timestamp=timestamp,
        replacement_bos_id=replacement_bos_id,
    )
