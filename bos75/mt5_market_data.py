from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import Candle
from .mt5_adapter import MT5AdapterConfig, MT5AdapterError


SUPPORTED_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M2": "TIMEFRAME_M2",
    "M3": "TIMEFRAME_M3",
    "M4": "TIMEFRAME_M4",
    "M5": "TIMEFRAME_M5",
    "M6": "TIMEFRAME_M6",
    "M10": "TIMEFRAME_M10",
    "M12": "TIMEFRAME_M12",
    "M15": "TIMEFRAME_M15",
    "M20": "TIMEFRAME_M20",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H2": "TIMEFRAME_H2",
    "H3": "TIMEFRAME_H3",
    "H4": "TIMEFRAME_H4",
    "H6": "TIMEFRAME_H6",
    "H8": "TIMEFRAME_H8",
    "H12": "TIMEFRAME_H12",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}


@dataclass(frozen=True)
class MT5CandleBatch:
    symbol: str
    timeframe: str
    candles: list[Candle]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "count": len(self.candles),
            "candles": [
                {
                    "symbol": candle.symbol,
                    "timestamp": candle.timestamp,
                    "index": candle.index,
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                }
                for candle in self.candles
            ],
        }


class MT5MarketDataAdapter:
    """Reads closed OHLC candles from the MetaTrader5 terminal."""

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

    def fetch_closed_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
        *,
        start_index: int = 0,
    ) -> MT5CandleBatch:
        if count <= 0:
            raise ValueError("count must be positive")

        normalized_timeframe = normalize_timeframe(timeframe)
        mt5_timeframe = timeframe_to_mt5(self.mt5, normalized_timeframe)
        symbol_info = self._ensure_symbol_visible(symbol)

        rates = self.mt5.copy_rates_from_pos(symbol, mt5_timeframe, 1, count)
        if rates is None or len(rates) == 0:
            raise MT5AdapterError(f"MT5 returned no closed candles for {symbol} {normalized_timeframe}")

        candles = rates_to_candles(
            symbol,
            rates,
            start_index=start_index,
            digits=getattr(symbol_info, "digits", None),
        )
        return MT5CandleBatch(symbol=symbol, timeframe=normalized_timeframe, candles=candles)

    def _ensure_symbol_visible(self, symbol: str) -> Any:
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise MT5AdapterError(f"symbol {symbol} is not available in MT5")
        if getattr(info, "visible", False):
            return info
        if not self.mt5.symbol_select(symbol, True):
            raise MT5AdapterError(f"symbol {symbol} is not visible and could not be selected")
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise MT5AdapterError(f"symbol {symbol} was selected but is not available in MT5")
        return info

    @staticmethod
    def _load_mt5_client() -> Any:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MT5AdapterError(
                "MetaTrader5 Python package is not installed. Install with: python -m pip install MetaTrader5"
            ) from exc
        return mt5


def normalize_timeframe(timeframe: str) -> str:
    normalized = timeframe.strip().upper()
    if normalized not in SUPPORTED_TIMEFRAMES:
        supported = ", ".join(sorted(SUPPORTED_TIMEFRAMES))
        raise ValueError(f"unsupported timeframe {timeframe!r}; supported values: {supported}")
    return normalized


def timeframe_to_mt5(mt5_client: Any, timeframe: str) -> int:
    normalized = normalize_timeframe(timeframe)
    constant_name = SUPPORTED_TIMEFRAMES[normalized]
    try:
        return int(getattr(mt5_client, constant_name))
    except AttributeError as exc:
        raise MT5AdapterError(f"MT5 client is missing {constant_name}") from exc


def rates_to_candles(
    symbol: str,
    rates: Iterable[Any],
    *,
    start_index: int = 0,
    digits: int | None = None,
) -> list[Candle]:
    sorted_rates = sorted(rates, key=lambda rate: int(_rate_value(rate, "time")))
    return [
        Candle(
            symbol=symbol,
            timestamp=_timestamp_to_utc_iso(int(_rate_value(rate, "time"))),
            index=start_index + offset,
            open=_price_to_str(_rate_value(rate, "open"), digits),
            high=_price_to_str(_rate_value(rate, "high"), digits),
            low=_price_to_str(_rate_value(rate, "low"), digits),
            close=_price_to_str(_rate_value(rate, "close"), digits),
        )
        for offset, rate in enumerate(sorted_rates)
    ]


def _rate_value(rate: Any, key: str) -> Any:
    if isinstance(rate, dict):
        return rate[key]
    try:
        return rate[key]
    except (TypeError, KeyError, IndexError, ValueError):
        return getattr(rate, key)


def _timestamp_to_utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _price_to_str(value: Any, digits: int | None) -> str:
    if digits is None:
        return str(value)
    return f"{float(value):.{int(digits)}f}"
