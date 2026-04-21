from __future__ import annotations

from dataclasses import dataclass

from .execution import StrategyEngine
from .models import (
    Candle,
    EventType,
    LogRecord,
    Position,
    StrategyState,
    StructureState,
    TradeSetup,
)
from .orders import ExecutionCommand
from .seeding import ExplicitStructureSeed, ExplicitStructureSeeder
from .structure import BOSDetector


@dataclass(frozen=True)
class ReplayStep:
    candle: Candle
    structure_override: StructureState | None = None
    bullish_leg_start_index: int | None = None
    bearish_leg_start_index: int | None = None


@dataclass(frozen=True)
class ReplaySnapshot:
    state: StrategyState
    pending_setup: TradeSetup | None
    position: Position | None
    commands: list[ExecutionCommand]
    logs: list[LogRecord]


class ReplayEngine:
    """Coordinates explicit structure seeds, closed candles, and lifecycle events."""

    def __init__(
        self,
        symbol: str,
        *,
        detector: BOSDetector | None = None,
        strategy: StrategyEngine | None = None,
    ) -> None:
        self.symbol = symbol
        self.detector = detector or BOSDetector()
        self.strategy = strategy or StrategyEngine(symbol)
        self.current_structure: StructureState | None = None
        self.candles: list[Candle] = []
        self.logs: list[LogRecord] = []
        self._strategy_log_cursor = 0

    def seed_explicit_structure(self, seed: ExplicitStructureSeed) -> StructureState:
        if seed.symbol != self.symbol:
            raise ValueError(f"replay symbol {self.symbol} cannot seed {seed.symbol}")

        result = ExplicitStructureSeeder.seed(seed)
        self.current_structure = result.structure
        self.logs.append(result.log)
        if self.strategy.state == StrategyState.WARMUP:
            self.strategy.complete_warmup(timestamp=None)
            self._drain_strategy_logs()
        return result.structure

    def feed(self, step: ReplayStep) -> ReplaySnapshot:
        self._require_symbol(step.candle.symbol)
        self.candles.append(step.candle)

        if step.structure_override is not None:
            self._require_symbol(step.structure_override.symbol)
            self.current_structure = step.structure_override
            self.logs.append(
                LogRecord(
                    event=EventType.STRUCTURE_UPDATED.value,
                    symbol=self.symbol,
                    timestamp=step.candle.timestamp,
                    message="External structure updated from explicit replay input.",
                    state_before=self.strategy.state,
                    state_after=self.strategy.state,
                    data={
                        "active_structural_high": self.current_structure.active_high.price,
                        "active_structural_low": self.current_structure.active_low.price,
                        "source": "explicit_replay_override",
                    },
                )
            )

        if self.current_structure is None:
            raise ValueError("replay cannot evaluate BOS before explicit structure is seeded")

        decision = self.detector.evaluate_closed_candle(
            self.candles,
            self.current_structure,
            bullish_leg_start_index=step.bullish_leg_start_index,
            bearish_leg_start_index=step.bearish_leg_start_index,
        )
        self.logs.extend(decision.logs)
        if decision.event is not None:
            self.strategy.on_bos(decision.event)
            self._drain_strategy_logs()
        return self.snapshot()

    def mark_entry_filled(self, timestamp: object) -> Position:
        if self.strategy.pending_setup is None:
            raise ValueError("cannot fill entry without an active setup")
        position = self.strategy.on_entry_filled(self.strategy.pending_setup.id, timestamp)
        self._drain_strategy_logs()
        return position

    def mark_setup_missed(self, timestamp: object, reason: str) -> None:
        if self.strategy.pending_setup is None:
            raise ValueError("cannot miss setup without an active setup")
        self.strategy.on_setup_missed(self.strategy.pending_setup.id, timestamp, reason)
        self._drain_strategy_logs()

    def mark_stop_hit(self, timestamp: object) -> None:
        if self.strategy.position is None:
            raise ValueError("cannot hit stop without an active position")
        self.strategy.on_stop_hit(self.strategy.position.id, timestamp)
        self._drain_strategy_logs()

    def mark_target_hit(self, timestamp: object) -> None:
        if self.strategy.position is None:
            raise ValueError("cannot hit target without an active position")
        self.strategy.on_target_hit(self.strategy.position.id, timestamp)
        self._drain_strategy_logs()

    def snapshot(self) -> ReplaySnapshot:
        return ReplaySnapshot(
            state=self.strategy.state,
            pending_setup=self.strategy.pending_setup,
            position=self.strategy.position,
            commands=list(self.strategy.commands),
            logs=list(self.logs),
        )

    def serialized_logs(self) -> list[dict]:
        return [log.to_dict() for log in self.logs]

    def serialized_commands(self) -> list[dict]:
        return [command.to_dict() for command in self.strategy.commands]

    def _drain_strategy_logs(self) -> None:
        new_logs = self.strategy.logs[self._strategy_log_cursor :]
        self.logs.extend(new_logs)
        self._strategy_log_cursor = len(self.strategy.logs)

    def _require_symbol(self, symbol: str) -> None:
        if symbol != self.symbol:
            raise ValueError(f"replay symbol {self.symbol} cannot process {symbol}")
