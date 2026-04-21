from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import EventType, LogRecord, StructureLevel, StructureState


@dataclass(frozen=True)
class ExplicitStructureSeed:
    symbol: str
    active_high_price: str
    active_high_timestamp: Any
    active_high_index: int
    active_low_price: str
    active_low_timestamp: Any
    active_low_index: int


@dataclass(frozen=True)
class StructureSeedResult:
    structure: StructureState
    log: LogRecord


class ExplicitStructureSeeder:
    """Creates structure state only from explicit external structure inputs."""

    @staticmethod
    def seed(seed: ExplicitStructureSeed) -> StructureSeedResult:
        structure = StructureState(
            symbol=seed.symbol,
            active_high=StructureLevel(
                name="ASH",
                price=seed.active_high_price,
                timestamp=seed.active_high_timestamp,
                candle_index=seed.active_high_index,
            ),
            active_low=StructureLevel(
                name="ASL",
                price=seed.active_low_price,
                timestamp=seed.active_low_timestamp,
                candle_index=seed.active_low_index,
            ),
        )
        return StructureSeedResult(
            structure=structure,
            log=LogRecord(
                event=EventType.STRUCTURE_SEEDED.value,
                symbol=seed.symbol,
                timestamp=None,
                message="External structure seeded from explicit ASH/ASL inputs.",
                data={
                    "active_structural_high": structure.active_high.price,
                    "active_structural_high_timestamp": structure.active_high.timestamp,
                    "active_structural_high_index": structure.active_high.candle_index,
                    "active_structural_low": structure.active_low.price,
                    "active_structural_low_timestamp": structure.active_low.timestamp,
                    "active_structural_low_index": structure.active_low.candle_index,
                    "source": "explicit",
                },
            ),
        )
