# BOS 75% Retracement Strategy Restatement

## Plain-English Rules

The strategy trades only after an external structure break.

It maintains an active structural high (ASH) and active structural low (ASL). A bullish BOS is valid only when a closed candle closes above the current ASH. A bearish BOS is valid only when a closed candle closes below the current ASL. Wick-only breaks do not count.

After a valid bullish BOS, the strategy identifies the protected low of the bullish expansion leg that produced the close above ASH. It places a buy limit at the 75% retracement of the leg, with stop loss at the protected low and take profit at the broken ASH.

After a valid bearish BOS, the strategy identifies the protected high of the bearish expansion leg that produced the close below ASL. It places a sell limit at the 75% retracement of the leg, with stop loss at the protected high and take profit at the broken ASL.

Only pending limit orders are used. The strategy never enters by market order, never chases a missed retracement, and does not manage trades after fill beyond the fixed stop loss and take profit.

Each symbol may have at most one active pending setup and at most one live position. A new valid BOS before entry cancels and replaces the existing pending setup. An opposite valid BOS before entry cancels the pending setup and creates a new setup only if that opposite BOS is valid.

## Formal Event And State Summary

Minimum states:

- `WARMUP`
- `WAITING_FOR_BULLISH_OR_BEARISH_BOS`
- `WAITING_FOR_BULLISH_RETRACE_ENTRY`
- `WAITING_FOR_BEARISH_RETRACE_ENTRY`
- `IN_BULLISH_TRADE`
- `IN_BEARISH_TRADE`

Minimum named events:

- `valid_bullish_bos`
- `valid_bearish_bos`
- `pending_order_placed`
- `pending_order_canceled`
- `bullish_entry_filled`
- `bearish_entry_filled`
- `stop_hit`
- `target_hit`
- `setup_missed`

State transitions are caused only by named events and must be logged. BOS checks log the candle timestamp, active structural levels before the check, direction, broken level, expansion leg boundaries, protected extreme, and resulting setup levels.

## Ambiguities That Change Trading Behavior

1. Initial ASH/ASL seeding is not fully specified.
   - The spec forbids silently inventing levels with fractal, zigzag, pivot, or generic local high/low logic.
   - Different seeding rules can materially change the first valid BOS and all later trades.

2. Expansion-leg start detection is not fully specified.
   - The spec defines the protected extreme as the extreme of the expansion leg that directly produced the BOS.
   - It does not define an automatic rule for where that leg starts.
   - Choosing a convenience rule would change stops, entries, targets, risk, and trade validity.

3. Post-BOS ASH/ASL update rules are not fully specified.
   - The spec says ASH/ASL are structure levels, not arbitrary pivots.
   - It does not yet define exactly when a newly created structural high/low replaces the old one after BOS.

4. Candle-only backtest sequencing is not fully specified.
   - In live MT5, tick order determines whether an entry, stop, target, or missed setup happens first inside a candle.
   - With OHLC-only replay, candles can contain both entry and target or stop and target prices without revealing sequence.

## Implementation Assumptions For The Initial Build

The initial implementation will not invent external structure. It will support explicitly seeded ASH/ASL and explicitly bounded expansion legs. This keeps BOS validation, setup geometry, state transitions, lifecycle rules, and logging testable while leaving automatic seeding isolated for confirmation.

The automatic seeding module will remain a documented boundary until a precise seeding rule is confirmed.

The initial replay engine will prefer explicit lifecycle events for fills, stops, targets, and missed setups instead of guessing intrabar order from OHLC candles.
