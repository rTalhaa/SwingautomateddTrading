from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Candle, LogRecord
from .mt5_adapter import MT5AdapterConfig
from .mt5_market_data import MT5MarketDataAdapter
from .orders import ExecutionCommand
from .persistence import (
    JsonStateStore,
    RuntimeState,
    candle_to_dict,
    trade_setup_to_dict,
)
from .replay import ReplayEngine, ReplayStep
from .seeding import ExplicitStructureSeed


@dataclass(frozen=True)
class DryRunLiveConfig:
    symbol: str
    timeframe: str
    state_path: Path
    lookback: int = 20
    terminal_path: str | None = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    seed: ExplicitStructureSeed | None = None
    bullish_leg_start_index: int | None = None
    bearish_leg_start_index: int | None = None


@dataclass(frozen=True)
class DryRunLiveResult:
    symbol: str
    timeframe: str
    state_path: Path
    fetched_count: int
    processed_count: int
    skipped_count: int
    last_processed_candle_timestamp: str | None
    next_candle_index: int
    new_commands: list[ExecutionCommand]
    new_logs: list[LogRecord]
    state: RuntimeState

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "state_path": str(self.state_path),
            "dry_run": True,
            "fetched_count": self.fetched_count,
            "processed_count": self.processed_count,
            "skipped_count": self.skipped_count,
            "last_processed_candle_timestamp": self.last_processed_candle_timestamp,
            "next_candle_index": self.next_candle_index,
            "pending_setup": trade_setup_to_dict(self.state.pending_setup),
            "position_open": self.state.position is not None,
            "new_commands": [command.to_dict() for command in self.new_commands],
            "new_logs": [log.to_dict() for log in self.new_logs],
        }


class DryRunLiveLoop:
    def __init__(
        self,
        config: DryRunLiveConfig,
        *,
        state_store: JsonStateStore | None = None,
        market_data: MT5MarketDataAdapter | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store or JsonStateStore(config.state_path)
        self.market_data = market_data or MT5MarketDataAdapter(
            MT5AdapterConfig(terminal_path=config.terminal_path)
        )

    def run_once(self) -> DryRunLiveResult:
        state = self._load_or_initialize_state()
        replay = replay_from_runtime_state(state)
        previous_command_count = len(replay.strategy.commands)
        previous_log_count = len(replay.logs)

        self.market_data.connect()
        try:
            batch = self.market_data.fetch_closed_candles(
                symbol=self.config.symbol,
                timeframe=self.config.timeframe,
                count=self.config.lookback,
            )
        finally:
            self.market_data.shutdown()

        new_candles = [
            candle
            for candle in batch.candles
            if state.last_processed_candle_timestamp is None
            or str(candle.timestamp) > state.last_processed_candle_timestamp
        ]

        last_processed = state.last_processed_candle_timestamp
        next_index = state.next_candle_index
        for candle in new_candles:
            indexed_candle = _with_index(candle, next_index)
            replay.feed(
                ReplayStep(
                    candle=indexed_candle,
                    bullish_leg_start_index=self.config.bullish_leg_start_index,
                    bearish_leg_start_index=self.config.bearish_leg_start_index,
                )
            )
            last_processed = str(indexed_candle.timestamp)
            next_index += 1

        updated_state = runtime_state_from_replay(
            replay,
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            last_processed_candle_timestamp=last_processed,
            next_candle_index=next_index,
        )
        self.state_store.save(updated_state)

        return DryRunLiveResult(
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            state_path=self.config.state_path,
            fetched_count=len(batch.candles),
            processed_count=len(new_candles),
            skipped_count=len(batch.candles) - len(new_candles),
            last_processed_candle_timestamp=last_processed,
            next_candle_index=next_index,
            new_commands=replay.strategy.commands[previous_command_count:],
            new_logs=replay.logs[previous_log_count:],
            state=updated_state,
        )

    def _load_or_initialize_state(self) -> RuntimeState:
        existing = self.state_store.load()
        if existing is not None:
            if existing.symbol != self.config.symbol:
                raise ValueError(
                    f"state symbol {existing.symbol} does not match config symbol {self.config.symbol}"
                )
            if existing.timeframe != self.config.timeframe:
                raise ValueError(
                    f"state timeframe {existing.timeframe} does not match config timeframe {self.config.timeframe}"
                )
            return existing

        if self.config.seed is None:
            raise ValueError("first dry-run live execution requires an explicit structure seed")

        replay = ReplayEngine(self.config.symbol)
        structure = replay.seed_explicit_structure(self.config.seed)
        return runtime_state_from_replay(
            replay,
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            last_processed_candle_timestamp=None,
            next_candle_index=0,
            structure=structure,
        )


def runtime_state_from_replay(
    replay: ReplayEngine,
    *,
    symbol: str,
    timeframe: str,
    last_processed_candle_timestamp: str | None,
    next_candle_index: int,
    structure: Any | None = None,
) -> RuntimeState:
    snapshot = replay.snapshot()
    current_structure = structure or replay.current_structure
    if current_structure is None:
        raise ValueError("cannot persist runtime state without structure")
    return RuntimeState(
        symbol=symbol,
        timeframe=timeframe,
        structure=current_structure,
        last_processed_candle_timestamp=last_processed_candle_timestamp,
        next_candle_index=next_candle_index,
        strategy_state=snapshot.state,
        pending_setup=snapshot.pending_setup,
        position=snapshot.position,
        candles=list(replay.candles),
        commands=list(snapshot.commands),
        logs=list(snapshot.logs),
    )


def replay_from_runtime_state(state: RuntimeState) -> ReplayEngine:
    replay = ReplayEngine(state.symbol)
    replay.current_structure = state.structure
    replay.candles = list(state.candles)
    replay.logs = list(state.logs)
    replay.strategy.state = state.strategy_state
    replay.strategy.pending_setup = state.pending_setup
    replay.strategy.position = state.position
    replay.strategy.commands = list(state.commands)
    replay.strategy.logs = []
    replay._strategy_log_cursor = 0
    return replay


def _with_index(candle: Candle, index: int) -> Candle:
    return Candle(
        symbol=candle.symbol,
        timestamp=candle.timestamp,
        index=index,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
    )
