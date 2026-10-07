# PANTHER Precision Standard

PANTHER must be built as a risk-controlled research and execution system, not a
prediction toy. Every trade path has to be explainable, measurable, and blocked
when the evidence is weak.

## Non-Negotiable Rules

- No live trade path can bypass backend config, broker checks, manual approval,
  strategy trust, volume caps, and the live unlock phrase.
- No strategy can be promoted from research unless it survives execution-cost
  assumptions and recent out-of-sample scoring.
- No signal should be described as guaranteed, certain, or risk-free.
- Every order must carry entry, stop loss, take profit, volume, rationale, and
  journal trace.
- Every rejected decision must say why it was rejected.
- Live execution must remain locked until a separate demo-evidence gate passes.

## Research Precision

Strategy scorecards must include:

- trades tested
- win rate
- gross net R
- net R after spread and slippage assumptions
- profit factor
- max drawdown in R
- recent out-of-sample net R
- precision grade
- approval status

Approval requires positive total net R and positive recent out-of-sample net R.
If either fails, the strategy cannot unlock execution.

## Execution Precision

Before any broker execution is allowed, PANTHER must verify:

- broker connection
- account mode
- symbol availability
- market session availability
- position count limits
- per-trade volume limits
- manual approval
- emergency stop availability

Manual approval is not a risk bypass. The paper position book enforces the
configured total-position cap and per-symbol cap, rejects invalid stop/target
geometry, rejects non-positive volume, and prevents duplicate journal entries.

## Demo Evidence Gate

Only closed demo trades count toward promotion. The default gate requires:

- at least 30 closed trades
- at least 14 separate demo trading days
- profit factor of at least 1.2
- net performance of at least 5R
- win rate of at least 35%
- maximum drawdown no greater than 6R

The gate is computed from stop-normalized R values, excludes open positions, and
returns explicit reasons for every failed threshold. A passing research score
alone cannot unlock live trading without passing this independent execution
evidence gate.

MT5 history imports must be audit-grade. A broker history item can count only
when PANTHER can identify it as a PANTHER-tagged closed trade and reconstruct
entry, stop-loss, take-profit, close price, realized PnL, and close time. Trades
without stop-loss metadata are skipped because they cannot be converted into a
truthful risk-normalized result.

## Current Build Status

The current build is demo-first and intentionally conservative. The strategy
trust gate can block trades even when a signal exists. That is correct behavior:
unproven setups should be stopped before execution.
