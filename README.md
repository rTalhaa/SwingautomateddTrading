# BOS 75% Retracement Strategy

This repository contains a structure-based strategy core for the BOS 75% retracement MT5 system.

The current implementation intentionally does not invent external structure with pivots, fractals, zigzags, or indicators. It supports explicitly seeded ASH/ASL levels and explicitly bounded expansion legs while the automatic seeding rule remains unresolved.

## Current Modules

- `bos75/structure.py` - close-confirmed BOS checks against active structural levels
- `bos75/setup_generation.py` - 75% retracement entry, stop, and target geometry
- `bos75/execution.py` - one-symbol lifecycle state machine
- `bos75/orders.py` - broker-facing pending limit and cancel command models
- `bos75/mt5_adapter.py` - optional MetaTrader5 Python adapter for order commands
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

Replay output includes:

- current strategy state
- active pending setup or position
- broker-facing order commands
- replayable decision and state-transition logs

## MT5 Adapter

The MT5 Python bridge is optional:

```powershell
python -m pip install ".[mt5]"
```

The adapter executes only the broker command layer:

- `place_pending_limit` becomes an MT5 pending buy/sell limit request
- `cancel_pending_order` removes a pending order matching the BOS75 magic/comment tag

It does not add market entries, trailing stops, partial exits, or risk-based position sizing.

Safe terminal check:

```powershell
python -m bos75.cli mt5-check
```

This initializes the terminal and prints connection/account metadata, but sends no order requests.

Safe original-terminal smoke test:

```powershell
python -m bos75.cli mt5-smoke --symbol EURUSD
```

This builds a far-away pending limit request and validates it through MT5 `order_check`; it still sends no order.

Opt-in original-terminal integration test:

```powershell
$env:BOS75_MT5_INTEGRATION='1'; python -m unittest tests.test_mt5_original_integration -v
```

## Open Strategy Decisions

Before automatic live structure detection can be finalized, the project needs precise rules for:

- initial ASH/ASL seeding
- expansion-leg start detection
- post-BOS ASH/ASL updates
- OHLC replay ordering when one candle touches multiple lifecycle prices
