from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .orders import (
    CancelPendingOrderCommand,
    ExecutionCommand,
    OrderCommandType,
    PendingOrderType,
    PlacePendingLimitCommand,
)


MT5_ORDER_CHECK_DONE = 0


class MT5AdapterError(RuntimeError):
    """Raised when the MT5 adapter cannot complete a broker action."""


@dataclass(frozen=True)
class MT5AdapterConfig:
    terminal_path: str | None = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    login: int | None = None
    password: str | None = None
    server: str | None = None
    magic_number: int = 750075
    volume: float = 0.01
    deviation: int = 20


@dataclass(frozen=True)
class MT5ExecutionResult:
    command_id: str
    command_type: OrderCommandType
    ok: bool
    retcode: int | None = None
    order_ticket: int | None = None
    request: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class MT5OrderAdapter:
    """Executes broker-facing commands through the MetaTrader5 Python package."""

    def __init__(self, config: MT5AdapterConfig | None = None, mt5_client: Any | None = None) -> None:
        self.config = config or MT5AdapterConfig()
        self.mt5 = mt5_client or self._load_mt5_client()

    def connect(self) -> None:
        initialize_kwargs = {}
        if self.config.terminal_path:
            initialize_kwargs["path"] = self.config.terminal_path
        if not self.mt5.initialize(**initialize_kwargs):
            raise MT5AdapterError(f"MT5 initialize failed: {self.mt5.last_error()}")

        if self.config.login is not None:
            login_kwargs: dict[str, Any] = {"login": self.config.login}
            if self.config.password is not None:
                login_kwargs["password"] = self.config.password
            if self.config.server is not None:
                login_kwargs["server"] = self.config.server
            if not self.mt5.login(**login_kwargs):
                raise MT5AdapterError(f"MT5 login failed: {self.mt5.last_error()}")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def execute(self, command: ExecutionCommand) -> MT5ExecutionResult:
        if command.command_type == OrderCommandType.PLACE_PENDING_LIMIT:
            return self.place_pending_limit(command)
        if command.command_type == OrderCommandType.CANCEL_PENDING_ORDER:
            return self.cancel_pending_order(command)
        raise MT5AdapterError(f"unsupported command type {command.command_type}")

    def place_pending_limit(self, command: PlacePendingLimitCommand) -> MT5ExecutionResult:
        request = self.build_place_request(command)
        result = self.mt5.order_send(request)
        retcode = getattr(result, "retcode", None)
        ok = retcode in {
            self.mt5.TRADE_RETCODE_DONE,
            self.mt5.TRADE_RETCODE_PLACED,
        }
        if not ok:
            return MT5ExecutionResult(
                command_id=command.id,
                command_type=command.command_type,
                ok=False,
                retcode=retcode,
                request=request,
                message=f"pending limit placement failed with retcode {retcode}",
            )

        return MT5ExecutionResult(
            command_id=command.id,
            command_type=command.command_type,
            ok=True,
            retcode=retcode,
            order_ticket=getattr(result, "order", None),
            request=request,
            message="pending limit placement accepted by MT5",
        )

    def check_pending_limit(self, command: PlacePendingLimitCommand) -> MT5ExecutionResult:
        request = self.build_place_request(command)
        result = self.mt5.order_check(request)
        retcode = getattr(result, "retcode", None)
        comment = getattr(result, "comment", "")
        ok = retcode == MT5_ORDER_CHECK_DONE
        return MT5ExecutionResult(
            command_id=command.id,
            command_type=command.command_type,
            ok=ok,
            retcode=retcode,
            request=request,
            message=comment if comment else f"order_check retcode {retcode}",
        )

    def cancel_pending_order(self, command: CancelPendingOrderCommand) -> MT5ExecutionResult:
        ticket = self._find_pending_order_ticket(command)
        if ticket is None:
            return MT5ExecutionResult(
                command_id=command.id,
                command_type=command.command_type,
                ok=False,
                request={},
                message="pending order not found for cancellation",
            )

        request = {"action": self.mt5.TRADE_ACTION_REMOVE, "order": ticket}
        result = self.mt5.order_send(request)
        retcode = getattr(result, "retcode", None)
        ok = retcode == self.mt5.TRADE_RETCODE_DONE
        return MT5ExecutionResult(
            command_id=command.id,
            command_type=command.command_type,
            ok=ok,
            retcode=retcode,
            order_ticket=ticket,
            request=request,
            message="pending order cancellation accepted by MT5"
            if ok
            else f"pending order cancellation failed with retcode {retcode}",
        )

    def build_place_request(self, command: PlacePendingLimitCommand) -> dict[str, Any]:
        order_type = (
            self.mt5.ORDER_TYPE_BUY_LIMIT
            if command.order_type == PendingOrderType.BUY_LIMIT
            else self.mt5.ORDER_TYPE_SELL_LIMIT
        )
        return {
            "action": self.mt5.TRADE_ACTION_PENDING,
            "symbol": command.symbol,
            "volume": self.config.volume,
            "type": order_type,
            "price": float(command.entry),
            "sl": float(command.stop_loss),
            "tp": float(command.take_profit),
            "deviation": self.config.deviation,
            "magic": self.config.magic_number,
            "comment": self.comment_for_setup(command.setup_id),
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_RETURN,
        }

    def select_first_available_symbol(self, preferred_symbols: list[str] | None = None) -> Any:
        symbols = preferred_symbols or ["EURUSD", "GBPUSD", "USDJPY"]
        for symbol in symbols:
            info = self.mt5.symbol_info(symbol)
            if info is None:
                continue
            if not getattr(info, "visible", False):
                self.mt5.symbol_select(symbol, True)
                info = self.mt5.symbol_info(symbol)
            if info is not None and getattr(info, "visible", False):
                return info
        raise MT5AdapterError(f"no available MT5 symbol found from {symbols}")

    def _find_pending_order_ticket(self, command: CancelPendingOrderCommand) -> int | None:
        orders = self.mt5.orders_get(symbol=command.symbol)
        if not orders:
            return None

        expected_comment = self.comment_for_setup(command.setup_id)
        for order in orders:
            if getattr(order, "magic", None) != self.config.magic_number:
                continue
            if getattr(order, "comment", None) != expected_comment:
                continue
            return int(getattr(order, "ticket"))
        return None

    @staticmethod
    def comment_for_setup(setup_id: str) -> str:
        digest = hashlib.sha1(setup_id.encode("utf-8")).hexdigest()[:16]
        return f"BOS75:{digest}"

    @staticmethod
    def _load_mt5_client() -> Any:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MT5AdapterError(
                "MetaTrader5 Python package is not installed. Install with: python -m pip install MetaTrader5"
            ) from exc
        return mt5
