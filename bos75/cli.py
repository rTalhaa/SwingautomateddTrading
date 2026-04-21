from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import Candle, Direction, Position, StrategyState, StructureLevel, StructureState, TradeSetup
from .mt5_adapter import MT5AdapterConfig, MT5OrderAdapter
from .mt5_market_data import MT5MarketDataAdapter
from .orders import PendingOrderType, PlacePendingLimitCommand
from .replay import ReplayEngine, ReplayStep
from .seeding import ExplicitStructureSeed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bos75.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser("replay", help="Run an explicit seeded replay fixture")
    replay_parser.add_argument("fixture", type=Path)
    replay_parser.add_argument("--output", type=Path, help="Optional path to write replay result JSON")

    mt5_parser = subparsers.add_parser("mt5-check", help="Verify MT5 terminal initialization")
    mt5_parser.add_argument(
        "--terminal-path",
        default=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        help="Path to terminal64.exe",
    )

    smoke_parser = subparsers.add_parser(
        "mt5-smoke",
        help="Run a safe MT5 original-terminal smoke test with order_check only",
    )
    smoke_parser.add_argument(
        "--terminal-path",
        default=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        help="Path to terminal64.exe",
    )
    smoke_parser.add_argument("--symbol", default="EURUSD", help="Preferred symbol for order_check")

    candles_parser = subparsers.add_parser(
        "mt5-candles",
        help="Fetch closed candles from MT5 as JSON",
    )
    candles_parser.add_argument("--symbol", default="EURUSD", help="Symbol to fetch")
    candles_parser.add_argument("--timeframe", default="M15", help="MT5 timeframe such as M1, M15, H1, H4")
    candles_parser.add_argument("--count", type=int, default=20, help="Number of closed candles to fetch")
    candles_parser.add_argument("--start-index", type=int, default=0, help="Index to assign to the first candle")
    candles_parser.add_argument(
        "--terminal-path",
        default=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        help="Path to terminal64.exe",
    )
    candles_parser.add_argument("--output", type=Path, help="Optional path to write candle JSON")

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
    if args.command == "mt5-check":
        result = check_mt5(args.terminal_path)
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 0
    if args.command == "mt5-smoke":
        result = smoke_mt5_order_check(args.terminal_path, args.symbol)
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 0
    if args.command == "mt5-candles":
        result = fetch_mt5_candles(
            terminal_path=args.terminal_path,
            symbol=args.symbol,
            timeframe=args.timeframe,
            count=args.count,
            start_index=args.start_index,
        )
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


def check_mt5(terminal_path: str | None) -> dict[str, Any]:
    adapter = MT5OrderAdapter(MT5AdapterConfig(terminal_path=terminal_path))
    adapter.connect()
    try:
        terminal_info = adapter.mt5.terminal_info()
        account_info = adapter.mt5.account_info()
        return {
            "ok": True,
            "terminal_name": getattr(terminal_info, "name", None),
            "terminal_path": getattr(terminal_info, "path", None),
            "connected": getattr(terminal_info, "connected", None),
            "trade_allowed": getattr(terminal_info, "trade_allowed", None),
            "account_login": getattr(account_info, "login", None) if account_info else None,
            "account_server": getattr(account_info, "server", None) if account_info else None,
        }
    finally:
        adapter.shutdown()


def smoke_mt5_order_check(terminal_path: str | None, symbol: str = "EURUSD") -> dict[str, Any]:
    adapter = MT5OrderAdapter(MT5AdapterConfig(terminal_path=terminal_path))
    adapter.connect()
    try:
        symbol_info = adapter.select_first_available_symbol([symbol, "EURUSD", "GBPUSD", "USDJPY"])
        tick = adapter.mt5.symbol_info_tick(symbol_info.name)
        if tick is None:
            raise RuntimeError(f"MT5 did not return a tick for {symbol_info.name}")

        point = Decimal(str(symbol_info.point))
        entry = Decimal(str(tick.ask)) - point * Decimal("1000")
        stop = entry - point * Decimal("300")
        target = entry + point * Decimal("900")
        command = PlacePendingLimitCommand(
            id=f"cmd:check:{symbol_info.name}",
            symbol=symbol_info.name,
            order_type=PendingOrderType.BUY_LIMIT,
            setup_id=f"setup-check-{symbol_info.name}",
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            source_bos_id="bos-check",
            timestamp="mt5-smoke",
        )
        result = adapter.check_pending_limit(command)
        terminal_info = adapter.mt5.terminal_info()
        account_info = adapter.mt5.account_info()
        return {
            "ok": result.ok,
            "terminal_name": getattr(terminal_info, "name", None),
            "terminal_path": getattr(terminal_info, "path", None),
            "terminal_trade_allowed": getattr(terminal_info, "trade_allowed", None),
            "account_login": getattr(account_info, "login", None) if account_info else None,
            "account_server": getattr(account_info, "server", None) if account_info else None,
            "account_trade_allowed": getattr(account_info, "trade_allowed", None) if account_info else None,
            "account_trade_expert": getattr(account_info, "trade_expert", None) if account_info else None,
            "symbol": symbol_info.name,
            "order_check_retcode": result.retcode,
            "order_check_message": result.message,
            "request": result.request,
        }
    finally:
        adapter.shutdown()


def fetch_mt5_candles(
    *,
    terminal_path: str | None,
    symbol: str,
    timeframe: str,
    count: int,
    start_index: int = 0,
) -> dict[str, Any]:
    adapter = MT5MarketDataAdapter(MT5AdapterConfig(terminal_path=terminal_path))
    adapter.connect()
    try:
        batch = adapter.fetch_closed_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count,
            start_index=start_index,
        )
        return batch.to_dict()
    finally:
        adapter.shutdown()


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
