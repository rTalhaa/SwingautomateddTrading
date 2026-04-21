# AGENTS.md

## Project intent
This repository contains a structure-based MT5 trading strategy.

Primary rule:
- Do not convert discretionary market-structure language into generic fractal, zigzag, or pivot logic unless the spec explicitly instructs it.

## Working rules
- Read `STRATEGY_SPEC.md` before making any code changes.
- Treat the strategy spec as the source of truth.
- If code and spec disagree, prefer the spec and flag the mismatch.
- If any trading definition is ambiguous, stop and restate the ambiguity before implementing.
- Do not add indicators, filters, or optimizations unless explicitly requested.
- Use candle-close confirmation only for BOS.
- Wick-only breaks never count as BOS.
- Keep structure detection, execution, and tests separated into distinct modules.

## Required development flow
1. Restate the strategy in formal rules.
2. Identify ambiguities that materially change trading behavior.
3. Implement structure detection first.
4. Implement setup generation second.
5. Implement execution logic third.
6. Add replay tests and deterministic unit tests.
7. Verify logs explain every signal and non-signal.

## Testing expectations
Every material trading rule must have a test.
At minimum, test:
- wick-only non-BOS behavior
- bullish BOS behavior
- bearish BOS behavior
- protected low / high identification
- entry / stop / target calculations
- setup replacement
- opposite-BOS invalidation
- one-setup-per-symbol constraint

## Logging expectations
Every BOS decision, protected level, order level, invalidation, and state change must be logged in a replayable way.

## Refactoring rule
Do not rewrite the execution module when changing structure logic.
Do not rewrite the structure module when changing order placement logic.
Keep boundaries clean.

## Non-goals
Unless the user asks for them, do not add:
- CHoCH
- internal structure
- FVG
- order blocks
- indicators
- discretionary heuristics
- auto-optimization