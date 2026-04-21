# BOS 75% Retracement Strategy

This repository contains a structure-based strategy core for the BOS 75% retracement MT5 system.

The current implementation intentionally does not invent external structure with pivots, fractals, zigzags, or indicators. It supports explicitly seeded ASH/ASL levels and explicitly bounded expansion legs while the automatic seeding rule remains unresolved.

## Current Modules

- `bos75/structure.py` - close-confirmed BOS checks against active structural levels
- `bos75/setup_generation.py` - 75% retracement entry, stop, and target geometry
- `bos75/execution.py` - one-symbol lifecycle state machine
- `bos75/seeding.py` - explicit ASH/ASL seeding without automatic swing invention
- `bos75/replay.py` - deterministic replay coordinator for seeded closed-candle inputs
- `bos75/models.py` - shared domain models and replayable log records
- `docs/IMPLEMENTATION_RESTATEMENT.md` - required pre-coding restatement and ambiguity register
- `tests/` - deterministic tests for the implemented rules

## Verify

```powershell
python -m unittest discover -s tests -v
```

## Replay Fixture

```powershell
python -m bos75.cli replay examples/bullish_replay.json
```

## Open Strategy Decisions

Before automatic live structure detection can be finalized, the project needs precise rules for:

- initial ASH/ASL seeding
- expansion-leg start detection
- post-BOS ASH/ASL updates
- OHLC replay ordering when one candle touches multiple lifecycle prices
