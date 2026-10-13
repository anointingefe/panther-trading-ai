# Execution Safety Audit

## Status

This branch is a safety and signal-integrity correction, not evidence of a profitable strategy.
It does not enable live trading, increase leverage, loosen live approval, change the
30-second scan setting, or reduce the configured number of trade slots.
Do not activate live trading on the strength of unit tests alone.

The local coding environment and connected Windows machine were offline during preparation.
Regression tests are provided for GitHub Actions; consult the actual workflow result before
merging. A written test is not a passed test. MT5 terminal integration remains unverified.

## Corrections

- Never round lot size upward to a broker minimum or step. A budget too small for the
  minimum lot produces zero volume, not a larger order.
- Use MT5's account-currency loss calculation for sizing. Missing, non-finite, zero, or
  positive stop-loss P/L cannot fall back to maximum lots or guessed tick conversions.
- Reject invalid sides, non-finite prices, and incorrectly ordered stop/entry/target values.
  Recheck stop/target direction against the current bid/ask before sending.
- Broker position-query errors are errors, not an empty portfolio.
- Only an explicit invalid-filling retcode permits a filling-mode retry. No alternate-mode
  retry follows a missing order_send result. Placed/partial requests count as accepted
  requests, not guaranteed completed fills.
- Shared execution checks the whole account position count as well as the per-symbol cap.
  Disabled live settings prevent this path from submitting to a real account.
- Both auto paths use broker-reported equity. Demo sizing also applies the per-trade risk
  amount through the broker adapter. Live sizing no longer boosts risk above the configured
  per-trade percentage because a heuristic score is high.
- Demo evaluation applies the existing daily realized-P/L guard; live scans also apply the
  same symbol cooldown and isolate individual symbol failures.
- Cooldowns expire. Historical loss streaks alone no longer create a permanent lock, and
  the latest loss timestamp is not overwritten by an older loss.
- Positive-net symbol/session results are not rejected solely for a low win rate.
  Negative net symbol results remain blocked pending a separately validated recovery policy.
- A static development sentiment placeholder is neutral and explicitly missing data. It
  no longer contributes an invented positive market view.
- Historical smoothed win frequency stays diagnostic. It is not mixed with a technical
  score or used as calibrated Kelly odds. Legacy configuration fields and the internal
  _kelly_volume name remain readable for compatibility, but no Kelly claim is made.
- Empty, malformed, non-finite, unordered, and zero-range candle data cannot generate a
  trade. The volatility distance now includes gaps from the previous close.

## Outstanding Release Blockers

1. Shared portfolio risk in account currency, including all open positions and pending
   orders, fees, a slippage allowance, free margin, and correlated exposure. Reserve risk
   atomically before orders are sent. Position count is not a monetary risk limit.
2. Durable intent IDs and broker reconciliation. The no-retry fix applies within a single
   submission; a later scan or restarted process must not blindly repeat an unknown outcome.
   Partial fills and placed orders still require fill/remaining-volume reconciliation.
3. A single guarded submission path for every entry point. Exact-signal approval, live
   unlock, risk limits, and current account identity must be enforced at the final boundary.
4. Authoritative, account-specific trade history and daily equity baseline, including fees,
   partial closes, all open losses, deposits/withdrawals, and demo/live separation.
5. Fully closed, fresh bars for signal generation, tick-age and spread checks, and
   stop-distance/price-grid/margin preflight. Current price geometry checks do not guarantee
   that fill risk equals preflight risk or that stops execute at the requested price.
6. Research-to-execution identity: auto runners still instantiate SmaSentimentStrategy
   directly. Displayed research approval is not proof the exact executing parameters were
   independently validated. Bind signals to versioned strategies and datasets.
7. Chronological walk-forward validation with non-overlapping train/validation/holdout
   windows, realistic costs, rejected orders, and marked-to-market drawdown. A tail slice
   scored while selecting a winner is not an untouched final test.
8. Point-in-time verified news sources. Live execution currently receives a missing-data
   sentiment placeholder, not an autonomous internet research feed. Retrieved web text
   must never have permission to change risk settings or place orders.
9. Broker-confirmed protection management. Suggested trailing/breakeven stops must actually
   be acknowledged by MT5; the initial risk used for R metrics must be preserved.
10. Connection recovery, duplicate concurrent cycles, restart supervision, and alerts for
    unprotected positions or failed closes.

## Capacity and Performance Work

The requested design is configurable capacity (for example 15 opportunities), not a
mandatory trade quota. Raise the existing cap only together with the shared monetary-risk
allocator, not as a standalone config change. Rank candidates before executing them and
recheck execution conditions for each order. Increasing capacity must not automatically
increase total permitted loss.

Evaluate performance using net expectancy, average win/loss, profit factor, drawdown,
exposure, costs, sample size, and confidence calibration by strategy and market regime.
13 wins and 23 losses alone cannot establish profitability or identify its cause.
The next audit needs the actual demo trade export with entry/exit times and prices, initial
SL/TP, lots, symbol, strategy version, commissions, swaps, slippage, and exit reason.
Never tune against those same trades and report the result as independent proof.

## Verification

Run from the repository root:
    python -m pip install -r requirements-dev.txt
    python -m compileall -q panther_trading tests
    python -m pytest -q

The suite uses simulated/mocked brokers and does not fund accounts or place MT5 orders.
Then verify on a confirmed MT5 demo account: minimum/step lots, unsupported filling,
disconnection, timeout reconciliation, stop/target acceptance, simultaneous requests,
and partial fills. Keep live execution disabled until the outstanding boundaries are tested.

Primary MT5 references:
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
