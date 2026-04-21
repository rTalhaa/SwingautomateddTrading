## Summary

- 

## Validation

- [ ] `python -m unittest discover -s tests -v`

## Strategy Guardrails

- [ ] I read `STRATEGY_SPEC.md` before changing behavior.
- [ ] This change does not introduce fractal, zigzag, generic pivot, indicator, or optimization logic.
- [ ] BOS behavior still uses candle-close confirmation only.
- [ ] Any ambiguous trading definition is linked to a GitHub issue before implementation.
- [ ] Replayable logs and deterministic tests were added or updated for material trading-rule changes.
