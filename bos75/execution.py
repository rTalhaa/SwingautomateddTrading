from __future__ import annotations

from .models import (
    BOSEvent,
    Direction,
    EventType,
    LogRecord,
    Position,
    StrategyState,
    TradeSetup,
)
from .orders import (
    ExecutionCommand,
    cancel_pending_order_from_setup,
    place_pending_limit_from_setup,
)
from .setup_generation import SetupGenerator


class StrategyEngine:
    """Explicit lifecycle state machine for one symbol."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.state = StrategyState.WARMUP
        self.pending_setup: TradeSetup | None = None
        self.position: Position | None = None
        self.logs: list[LogRecord] = []
        self.commands: list[ExecutionCommand] = []

    def complete_warmup(self, timestamp: object | None = None) -> None:
        self._transition(
            event="warmup_complete",
            timestamp=timestamp,
            next_state=StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS,
            message="Warmup complete; strategy can evaluate live BOS events.",
        )

    def on_bos(self, bos: BOSEvent) -> TradeSetup | None:
        self._require_symbol(bos.symbol)

        if self.state == StrategyState.WARMUP:
            self.logs.append(
                LogRecord(
                    event=EventType.BOS_IGNORED.value,
                    symbol=self.symbol,
                    timestamp=bos.timestamp,
                    state_before=self.state,
                    state_after=self.state,
                    message="BOS ignored during warmup; live trades are disabled while seeding.",
                    data={"bos_id": bos.id, "direction": bos.direction.value},
                )
            )
            return None

        if self.position is not None:
            self.logs.append(
                LogRecord(
                    event=EventType.BOS_IGNORED.value,
                    symbol=self.symbol,
                    timestamp=bos.timestamp,
                    state_before=self.state,
                    state_after=self.state,
                    message="BOS ignored because one live position already exists for symbol.",
                    data={
                        "bos_id": bos.id,
                        "direction": bos.direction.value,
                        "position_id": self.position.id,
                    },
                )
            )
            return None

        if self.pending_setup is not None:
            reason = (
                "same_direction_replacement"
                if self.pending_setup.direction == bos.direction
                else "opposite_bos_invalidation"
            )
            self._cancel_pending(
                timestamp=bos.timestamp,
                reason=reason,
                replacement_bos_id=bos.id,
            )

        setup = SetupGenerator.from_bos(bos)
        self.pending_setup = setup
        command = place_pending_limit_from_setup(setup)
        self.commands.append(command)
        next_state = (
            StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY
            if setup.direction == Direction.BULLISH
            else StrategyState.WAITING_FOR_BEARISH_RETRACE_ENTRY
        )
        self._transition(
            event=EventType.PENDING_ORDER_PLACED.value,
            timestamp=bos.timestamp,
            next_state=next_state,
            message="Pending limit order placed from valid BOS setup.",
            data={
                "setup_id": setup.id,
                "bos_id": bos.id,
                "direction": setup.direction.value,
                "entry": setup.entry,
                "stop_loss": setup.stop_loss,
                "take_profit": setup.take_profit,
                "risk": setup.risk,
                "reward": setup.reward,
                "order_command_id": command.id,
                "order_command_type": command.command_type.value,
                "order_type": command.order_type.value,
            },
        )
        return setup

    def on_entry_filled(self, setup_id: str, timestamp: object) -> Position:
        if self.pending_setup is None:
            raise ValueError("cannot fill entry without a pending setup")
        if self.pending_setup.id != setup_id:
            raise ValueError("filled setup id does not match active pending setup")
        if self.position is not None:
            raise ValueError("cannot fill entry while a live position exists")

        setup = self.pending_setup
        self.pending_setup = None
        self.position = Position(id=f"position:{setup.id}", setup=setup, opened_at=timestamp)
        next_state = (
            StrategyState.IN_BULLISH_TRADE
            if setup.direction == Direction.BULLISH
            else StrategyState.IN_BEARISH_TRADE
        )
        event = (
            EventType.BULLISH_ENTRY_FILLED.value
            if setup.direction == Direction.BULLISH
            else EventType.BEARISH_ENTRY_FILLED.value
        )
        self._transition(
            event=event,
            timestamp=timestamp,
            next_state=next_state,
            message="Pending limit order filled; fixed SL and TP are now active.",
            data={"setup_id": setup.id, "position_id": self.position.id},
        )
        return self.position

    def on_setup_missed(self, setup_id: str, timestamp: object, reason: str) -> None:
        if self.pending_setup is None:
            raise ValueError("cannot miss setup without a pending setup")
        if self.pending_setup.id != setup_id:
            raise ValueError("missed setup id does not match active pending setup")

        setup = self.pending_setup
        self._cancel_pending(
            timestamp=timestamp,
            reason=f"setup_missed:{reason}",
            replacement_bos_id=None,
        )
        self._transition(
            event=EventType.SETUP_MISSED.value,
            timestamp=timestamp,
            next_state=StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS,
            message="Setup missed; no market order will be placed.",
            data={"setup_id": setup.id, "direction": setup.direction.value, "reason": reason},
        )

    def on_stop_hit(self, position_id: str, timestamp: object) -> None:
        self._close_position(
            expected_position_id=position_id,
            timestamp=timestamp,
            event=EventType.STOP_HIT.value,
            message="Position closed at fixed stop loss.",
        )

    def on_target_hit(self, position_id: str, timestamp: object) -> None:
        self._close_position(
            expected_position_id=position_id,
            timestamp=timestamp,
            event=EventType.TARGET_HIT.value,
            message="Position closed at fixed take profit.",
        )

    def _close_position(
        self,
        *,
        expected_position_id: str,
        timestamp: object,
        event: str,
        message: str,
    ) -> None:
        if self.position is None:
            raise ValueError("cannot close position when no live position exists")
        if self.position.id != expected_position_id:
            raise ValueError("closed position id does not match active position")

        position = self.position
        self.position = None
        self._transition(
            event=event,
            timestamp=timestamp,
            next_state=StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS,
            message=message,
            data={
                "position_id": position.id,
                "setup_id": position.setup.id,
                "direction": position.setup.direction.value,
            },
        )

    def _cancel_pending(
        self,
        *,
        timestamp: object,
        reason: str,
        replacement_bos_id: str | None,
    ) -> None:
        if self.pending_setup is None:
            raise ValueError("cannot cancel pending setup when none exists")

        canceled = self.pending_setup
        self.pending_setup = None
        command = cancel_pending_order_from_setup(
            canceled,
            reason=reason,
            timestamp=timestamp,
            replacement_bos_id=replacement_bos_id,
        )
        self.commands.append(command)
        self.logs.append(
            LogRecord(
                event=EventType.PENDING_ORDER_CANCELED.value,
                symbol=self.symbol,
                timestamp=timestamp,
                state_before=self.state,
                state_after=self.state,
                message="Pending order canceled before replacement setup.",
                data={
                    "setup_id": canceled.id,
                    "direction": canceled.direction.value,
                    "reason": reason,
                    "replacement_bos_id": replacement_bos_id,
                    "order_command_id": command.id,
                    "order_command_type": command.command_type.value,
                },
            )
        )

    def _transition(
        self,
        *,
        event: str,
        timestamp: object | None,
        next_state: StrategyState,
        message: str,
        data: dict | None = None,
    ) -> None:
        previous_state = self.state
        self.state = next_state
        self.logs.append(
            LogRecord(
                event=event,
                symbol=self.symbol,
                timestamp=timestamp,
                state_before=previous_state,
                state_after=next_state,
                message=message,
                data=data or {},
            )
        )

    def _require_symbol(self, symbol: str) -> None:
        if symbol != self.symbol:
            raise ValueError(f"engine symbol {self.symbol} cannot process event for {symbol}")
