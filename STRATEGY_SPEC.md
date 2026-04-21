# BOS 75% Retracement Strategy Specification

## 1) Objective

Build an automated MT5 strategy that trades only BOS-based retracement entries.

The strategy must:
- use external / swing structure only
- ignore internal structure unless a future revision explicitly adds it
- detect BOS by candle close only
- place a pending limit order at the 75% retracement of the BOS leg
- set stop loss at the protected extreme of the BOS leg
- set take profit at the broken structural level
- avoid discretionary interpretation not explicitly defined here

The strategy must not:
- use fixed n-bar fractal logic to define swings
- use generic pivot detection as a substitute for structure-based swing logic
- add indicators or filters that are not listed in this spec
- use wick-only breaks as BOS
- chase missed entries with market orders

---

## 2) Timeframe and scope

Configuration parameters:
- symbols: <CONFIGURABLE>
- analysis timeframe: <CONFIGURABLE>
- execution timeframe: same as analysis timeframe unless explicitly changed
- one active setup per symbol at a time
- one open position per symbol at a time

Default behavior:
- evaluate structure only on closed candles
- do not create, modify, or cancel structure intrabar

---

## 3) Core structure definitions

### 3.1 External structure only
The strategy must model only swing / external structure.

It must not define swing highs or swing lows by:
- "n candles on the left and right"
- generic local maxima/minima
- zigzag or fractal logic unless explicitly approved in a later revision

A swing becomes relevant only when price uses it in structure.

### 3.2 Active structural high / low
The strategy maintains:
- active structural high (ASH): the high that must be closed above to confirm bullish BOS
- active structural low (ASL): the low that must be closed below to confirm bearish BOS

ASH and ASL are structure levels, not arbitrary pivots.

### 3.3 Valid bullish BOS
A bullish BOS exists only when:
- a candle closes above the current ASH

A wick above ASH does not count.

### 3.4 Valid bearish BOS
A bearish BOS exists only when:
- a candle closes below the current ASL

A wick below ASL does not count.

### 3.5 Protected extreme
After BOS, the strategy must identify the protected extreme that caused the move.

For bullish BOS:
- protected low = the lowest low of the bullish expansion leg that ended in the candle close above ASH

For bearish BOS:
- protected high = the highest high of the bearish expansion leg that ended in the candle close below ASL

This protected extreme becomes the stop-loss anchor for the setup.

### 3.6 Expansion leg
The expansion leg is the directional price move that directly produced the valid BOS close.

For bullish BOS:
- the relevant leg is the upward leg ending in the BOS candle close above ASH

For bearish BOS:
- the relevant leg is the downward leg ending in the BOS candle close below ASL

The implementation must make the start and end of this leg explicit in code and logs.

---

## 4) Trade geometry

### 4.1 Bullish setup
After a valid bullish BOS:
- high_anchor = broken ASH
- low_anchor = protected low of the bullish expansion leg

Place:
- buy limit at 75% retracement of the BOS leg
- stop loss at low_anchor
- take profit at high_anchor

Formula:
- entry = high_anchor - 0.75 * (high_anchor - low_anchor)
- sl = low_anchor
- tp = high_anchor

Notes:
- this is a 75% retracement measured from the top of the leg back toward the protected low
- do not reinterpret this as a different coordinate system without documenting it

### 4.2 Bearish setup
After a valid bearish BOS:
- low_anchor = broken ASL
- high_anchor = protected high of the bearish expansion leg

Place:
- sell limit at 75% retracement of the BOS leg
- stop loss at high_anchor
- take profit at low_anchor

Formula:
- entry = low_anchor + 0.75 * (high_anchor - low_anchor)
- sl = high_anchor
- tp = low_anchor

### 4.3 Risk / reward
The implementation must preserve the intended 1:3 structure:
- risk = distance from entry to stop
- reward = distance from entry to target
- reward must equal 3x risk, subject only to rounding constraints from symbol tick size

---

## 5) Order lifecycle rules

### 5.1 Order type
Use pending limit orders only:
- buy limit for bullish setup
- sell limit for bearish setup

Do not enter with market orders.

### 5.2 One setup rule
For each symbol:
- allow only one active pending setup at a time
- allow only one live position at a time

### 5.3 Replacement rule
If a new valid BOS forms before the existing pending order is filled:
- cancel the existing pending order
- replace it with the new setup in the direction implied by the latest valid BOS

### 5.4 Opposite-BOS invalidation
If an opposite valid BOS forms before entry:
- cancel the pending order immediately
- create a new setup only if the opposite BOS itself is valid under this spec

### 5.5 Missed trade rule
If price reaches target without filling the retracement entry:
- mark the setup as missed
- do not chase with a market order
- wait for the next valid BOS

### 5.6 Fill-to-exit behavior
Once filled:
- leave SL and TP fixed unless a future revision explicitly adds management logic
- no break-even logic
- no partials
- no trailing stop
- no scale-in
- no scale-out

---

## 6) Structure state machine

Implement the strategy as an explicit state machine.

Minimum states:
- WARMUP
- WAITING_FOR_BULLISH_OR_BEARISH_BOS
- WAITING_FOR_BULLISH_RETRACE_ENTRY
- WAITING_FOR_BEARISH_RETRACE_ENTRY
- IN_BULLISH_TRADE
- IN_BEARISH_TRADE

Requirements:
- every state transition must be logged
- every transition must be caused by a named event
- no hidden state changes

Named events must include at least:
- valid_bullish_bos
- valid_bearish_bos
- pending_order_placed
- pending_order_canceled
- bullish_entry_filled
- bearish_entry_filled
- stop_hit
- target_hit
- setup_missed

---

## 7) Seeding and warmup

Initial structure seeding is a separate concern from live signal generation.

Rules:
- do not place live trades during seeding
- do not silently invent ASH/ASL with generic fractal logic
- seeding logic must be isolated in its own module or function
- the code must clearly document how ASH and ASL become initialized

Default instruction:
- if the initial seeding method materially changes trade behavior, stop and ask for confirmation before finalizing implementation

---

## 8) Logging requirements

The strategy must log:
- candle timestamp used for every BOS decision
- current ASH and ASL before each BOS check
- BOS direction and broken level price
- expansion leg start index / end index
- protected extreme price and timestamp
- entry, stop, target
- order placement
- order cancellation reason
- entry fill
- exit reason
- state transitions

Logs must be detailed enough to replay exactly why a trade was or was not taken.

---

## 9) Testing / validation requirements

Add deterministic tests or replay tests that prove all of the following:

1. Wick-only break above ASH does not trigger bullish BOS.
2. Wick-only break below ASL does not trigger bearish BOS.
3. Close above ASH triggers exactly one bullish BOS event.
4. Close below ASL triggers exactly one bearish BOS event.
5. Bullish BOS computes protected low from the correct expansion leg.
6. Bearish BOS computes protected high from the correct expansion leg.
7. Entry, stop, and target match the formulas in this spec.
8. New same-direction BOS replaces previous pending setup.
9. Opposite BOS cancels pending setup.
10. Missed retracement does not create a market chase.
11. Only one active setup exists per symbol.
12. Only one live position exists per symbol.

---

## 10) Non-goals

Do not implement:
- CHoCH
- internal structure
- FVG
- order blocks
- EMA / RSI / MACD filters
- session filters
- spread filters
- risk-based position sizing
- multi-target exits
- trade management after fill

These can be added only in later revisions.

---

## 11) Implementation guardrails

The implementation must not:
- translate "structure-based swing" into n-bar fractals
- translate "protected low/high" into nearest local pivot by convenience
- add discretionary interpretation not explicitly written here
- optimize or tune behavior without being asked
- change the formulas for entry, stop, or target

If any term remains ambiguous, restate the ambiguity before coding and propose 2-3 precise alternatives with examples.

---

## 12) Required pre-coding restatement

Before writing production code, restate this strategy as:
1. a plain-English rules summary
2. a formal event/state summary
3. a list of ambiguities that could change trading behavior
4. the exact assumptions chosen for implementation

Do not begin final implementation until that restatement is complete.