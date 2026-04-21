from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import Candle, Direction, Position, StrategyState, StructureLevel, StructureState, TradeSetup
from .replay import ReplayEngine, ReplayStep
from .seeding import ExplicitStructureSeed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bos75.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser("replay", help="Run an explicit seeded replay fixture")
    replay_parser.add_argument("fixture", type=Path)
    replay_parser.add_argument("--output", type=Path, help="Optional path to write replay result JSON")

    args = parser.parse_args(argv)
    if args.command == "replay":
        payload = json.loads(args.fixture.read_text(encoding="utf-8"))
        result = run_replay_payload(payload)
        output = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.write(output + "\n")
        return 0

    raise AssertionError(f"unhandled command {args.command}")


def run_replay_payload(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = payload["symbol"]
    replay = ReplayEngine(symbol)
    replay.seed_explicit_structure(_load_seed(symbol, payload["seed"]))

    for event in payload.get("events", []):
        event_type = event["type"]
        if event_type == "candle":
            replay.feed(
                ReplayStep(
                    candle=_load_candle(symbol, event["candle"]),
                    structure_override=_load_structure_override(symbol, event),
                    bullish_leg_start_index=event.get("bullish_leg_start_index"),
                    bearish_leg_start_index=event.get("bearish_leg_start_index"),
                )
            )
        elif event_type == "entry_filled":
            replay.mark_entry_filled(event["timestamp"])
        elif event_type == "setup_missed":
            replay.mark_setup_missed(event["timestamp"], event["reason"])
        elif event_type == "stop_hit":
            replay.mark_stop_hit(event["timestamp"])
        elif event_type == "target_hit":
            replay.mark_target_hit(event["timestamp"])
        else:
            raise ValueError(f"unsupported replay event type {event_type!r}")

    snapshot = replay.snapshot()
    return {
        "symbol": symbol,
        "state": _serialize_value(snapshot.state),
        "pending_setup": _serialize_setup(snapshot.pending_setup),
        "position": _serialize_position(snapshot.position),
        "commands": replay.serialized_commands(),
        "logs": replay.serialized_logs(),
    }


def _load_seed(symbol: str, payload: dict[str, Any]) -> ExplicitStructureSeed:
    return ExplicitStructureSeed(
        symbol=symbol,
        active_high_price=str(payload["active_high"]["price"]),
        active_high_timestamp=payload["active_high"]["timestamp"],
        active_high_index=int(payload["active_high"]["index"]),
        active_low_price=str(payload["active_low"]["price"]),
        active_low_timestamp=payload["active_low"]["timestamp"],
        active_low_index=int(payload["active_low"]["index"]),
    )


def _load_candle(symbol: str, payload: dict[str, Any]) -> Candle:
    return Candle(
        symbol=payload.get("symbol", symbol),
        timestamp=payload["timestamp"],
        index=int(payload["index"]),
        open=str(payload["open"]),
        high=str(payload["high"]),
        low=str(payload["low"]),
        close=str(payload["close"]),
    )


def _load_structure_override(symbol: str, event: dict[str, Any]) -> StructureState | None:
    payload = event.get("structure_override")
    if payload is None:
        return None
    return StructureState(
        symbol=symbol,
        active_high=StructureLevel(
            name="ASH",
            price=str(payload["active_high"]["price"]),
            timestamp=payload["active_high"]["timestamp"],
            candle_index=int(payload["active_high"]["index"]),
        ),
        active_low=StructureLevel(
            name="ASL",
            price=str(payload["active_low"]["price"]),
            timestamp=payload["active_low"]["timestamp"],
            candle_index=int(payload["active_low"]["index"]),
        ),
    )


def _serialize_setup(setup: TradeSetup | None) -> dict[str, Any] | None:
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
        "risk": str(setup.risk),
        "reward": str(setup.reward),
    }


def _serialize_position(position: Position | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "id": position.id,
        "opened_at": position.opened_at,
        "setup": _serialize_setup(position.setup),
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, StrategyState | Direction):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
