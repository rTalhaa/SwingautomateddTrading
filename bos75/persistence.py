from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import (
    Candle,
    Direction,
    LogRecord,
    Position,
    StrategyState,
    StructureLevel,
    StructureState,
    TradeSetup,
)
from .orders import (
    CancelPendingOrderCommand,
    ExecutionCommand,
    OrderCommandType,
    PendingOrderType,
    PlacePendingLimitCommand,
)


STATE_SCHEMA_VERSION = 1


@dataclass
class RuntimeState:
    symbol: str
    timeframe: str
    structure: StructureState
    last_processed_candle_timestamp: str | None = None
    next_candle_index: int = 0
    strategy_state: StrategyState = StrategyState.WARMUP
    pending_setup: TradeSetup | None = None
    position: Position | None = None
    candles: list[Candle] = field(default_factory=list)
    commands: list[ExecutionCommand] = field(default_factory=list)
    logs: list[LogRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "structure": structure_to_dict(self.structure),
            "last_processed_candle_timestamp": self.last_processed_candle_timestamp,
            "next_candle_index": self.next_candle_index,
            "strategy_state": self.strategy_state.value,
            "pending_setup": trade_setup_to_dict(self.pending_setup),
            "position": position_to_dict(self.position),
            "candles": [candle_to_dict(candle) for candle in self.candles],
            "commands": [command_to_dict(command) for command in self.commands],
            "logs": [log.to_dict() for log in self.logs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RuntimeState:
        schema_version = payload.get("schema_version")
        if schema_version != STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported state schema version {schema_version!r}")

        return cls(
            symbol=payload["symbol"],
            timeframe=payload["timeframe"],
            structure=structure_from_dict(payload["structure"]),
            last_processed_candle_timestamp=payload.get("last_processed_candle_timestamp"),
            next_candle_index=int(payload.get("next_candle_index", 0)),
            strategy_state=StrategyState(payload.get("strategy_state", StrategyState.WARMUP.value)),
            pending_setup=trade_setup_from_dict(payload.get("pending_setup")),
            position=position_from_dict(payload.get("position")),
            candles=[candle_from_dict(item) for item in payload.get("candles", [])],
            commands=[command_from_dict(item) for item in payload.get("commands", [])],
            logs=[log_record_from_dict(item) for item in payload.get("logs", [])],
        )


class JsonStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RuntimeState | None:
        if not self.path.exists():
            return None
        return RuntimeState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: RuntimeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.path)


def candle_to_dict(candle: Candle) -> dict[str, Any]:
    return {
        "symbol": candle.symbol,
        "timestamp": candle.timestamp,
        "index": candle.index,
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
    }


def candle_from_dict(payload: dict[str, Any]) -> Candle:
    return Candle(
        symbol=payload["symbol"],
        timestamp=payload["timestamp"],
        index=int(payload["index"]),
        open=payload["open"],
        high=payload["high"],
        low=payload["low"],
        close=payload["close"],
    )


def structure_to_dict(structure: StructureState) -> dict[str, Any]:
    return {
        "symbol": structure.symbol,
        "active_high": structure_level_to_dict(structure.active_high),
        "active_low": structure_level_to_dict(structure.active_low),
    }


def structure_from_dict(payload: dict[str, Any]) -> StructureState:
    return StructureState(
        symbol=payload["symbol"],
        active_high=structure_level_from_dict(payload["active_high"]),
        active_low=structure_level_from_dict(payload["active_low"]),
    )


def structure_level_to_dict(level: StructureLevel) -> dict[str, Any]:
    return {
        "name": level.name,
        "price": str(level.price),
        "timestamp": level.timestamp,
        "candle_index": level.candle_index,
    }


def structure_level_from_dict(payload: dict[str, Any]) -> StructureLevel:
    return StructureLevel(
        name=payload["name"],
        price=payload["price"],
        timestamp=payload["timestamp"],
        candle_index=int(payload["candle_index"]),
    )


def trade_setup_to_dict(setup: TradeSetup | None) -> dict[str, Any] | None:
    if setup is None:
        return None
    return {
        "id": setup.id,
        "symbol": setup.symbol,
        "direction": setup.direction.value,
        "entry": str(setup.entry),
        "stop_loss": str(setup.stop_loss),
        "take_profit": str(setup.take_profit),
        "high_anchor": str(setup.high_anchor),
        "low_anchor": str(setup.low_anchor),
        "source_bos_id": setup.source_bos_id,
        "created_at": setup.created_at,
    }


def trade_setup_from_dict(payload: dict[str, Any] | None) -> TradeSetup | None:
    if payload is None:
        return None
    return TradeSetup(
        id=payload["id"],
        symbol=payload["symbol"],
        direction=Direction(payload["direction"]),
        entry=Decimal(payload["entry"]),
        stop_loss=Decimal(payload["stop_loss"]),
        take_profit=Decimal(payload["take_profit"]),
        high_anchor=Decimal(payload["high_anchor"]),
        low_anchor=Decimal(payload["low_anchor"]),
        source_bos_id=payload["source_bos_id"],
        created_at=payload["created_at"],
    )


def position_to_dict(position: Position | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "id": position.id,
        "setup": trade_setup_to_dict(position.setup),
        "opened_at": position.opened_at,
    }


def position_from_dict(payload: dict[str, Any] | None) -> Position | None:
    if payload is None:
        return None
    setup = trade_setup_from_dict(payload["setup"])
    if setup is None:
        raise ValueError("position payload must contain setup")
    return Position(id=payload["id"], setup=setup, opened_at=payload["opened_at"])


def command_to_dict(command: ExecutionCommand) -> dict[str, Any]:
    return command.to_dict()


def command_from_dict(payload: dict[str, Any]) -> ExecutionCommand:
    command_type = OrderCommandType(payload["command_type"])
    if command_type == OrderCommandType.PLACE_PENDING_LIMIT:
        return PlacePendingLimitCommand(
            id=payload["id"],
            symbol=payload["symbol"],
            order_type=PendingOrderType(payload["order_type"]),
            setup_id=payload["setup_id"],
            entry=Decimal(payload["entry"]),
            stop_loss=Decimal(payload["stop_loss"]),
            take_profit=Decimal(payload["take_profit"]),
            source_bos_id=payload["source_bos_id"],
            timestamp=payload["timestamp"],
        )
    if command_type == OrderCommandType.CANCEL_PENDING_ORDER:
        return CancelPendingOrderCommand(
            id=payload["id"],
            symbol=payload["symbol"],
            setup_id=payload["setup_id"],
            reason=payload["reason"],
            timestamp=payload["timestamp"],
            replacement_bos_id=payload.get("replacement_bos_id"),
        )
    raise ValueError(f"unsupported command type {command_type}")


def log_record_from_dict(payload: dict[str, Any]) -> LogRecord:
    return LogRecord(
        event=payload["event"],
        symbol=payload["symbol"],
        timestamp=payload.get("timestamp"),
        message=payload["message"],
        state_before=_state_or_none(payload.get("state_before")),
        state_after=_state_or_none(payload.get("state_after")),
        data=payload.get("data", {}),
    )


def _state_or_none(value: str | None) -> StrategyState | None:
    if value is None:
        return None
    return StrategyState(value)
