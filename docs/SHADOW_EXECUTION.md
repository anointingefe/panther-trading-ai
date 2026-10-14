# PANTHER Shadow Execution and Broker Reconciliation

Shadow Execution is the proving layer between demo strategy validation and any future real-money execution.

## Safety model

Shadow mode connects to MT5 and runs the same signal, risk, sizing, and broker preflight path that a live trade would use, but it never calls `order_send`. Live trading remains controlled separately by `execution.allow_live_trading` and is currently disabled in `config/demo.yaml`.

For every qualifying signal Panther records:

- current MT5 bid/ask and quote age;
- spread in broker points;
- spread relative to stop distance;
- broker-normalized position size;
- broker minimum stop-distance compliance;
- SL/TP bracket validity at the current market price;
- MT5 `order_check` result when available;
- the hypothetical outcome after the signal, including win/loss/expiry/ambiguous resolution.

Only MT5-native samples count toward the Execution Green Flag. Simulated-broker samples can be useful for development but cannot unlock live readiness.

## Execution Green Flag

The default proving threshold requires:

- at least 50 MT5-native shadow samples;
- at least 99% broker preflight success;
- at least 99% fresh-quote coverage;
- 100% valid position sizing;
- 100% valid stop/target brackets;
- at least 20 broker reconciliation checks;
- no recorded reconciliation mismatch.

These thresholds are configurable under `shadow_execution` in `config/demo.yaml`.

## Broker reconciliation

Panther maintains a separate live-order ledger at `var/live_positions.json`. Before the live runner can add risk it compares that ledger with MT5 Panther-live positions and recent Panther-live closed history.

A live cycle is blocked when Panther finds any of the following:

- an MT5 Panther-live position with no matching local ledger record;
- an active local live record missing from MT5 open/closed history;
- duplicate broker order IDs;
- broker history or position retrieval failures.

Demo incubation positions are explicitly ignored by the live reconciliation layer.

## Duplicate protection

Accepted live orders are persisted immediately in the live ledger. Panther refuses a recent duplicate signal with the same symbol, side, stop, and target while the existing live record remains active.

## API

- `GET /api/shadow/status` — current shadow state.
- `POST /api/shadow/cycle` — run one zero-order shadow cycle.
- `POST /api/shadow/start` — start continuous shadow proving.
- `POST /api/shadow/stop` — stop continuous shadow proving.
- `GET /api/live/execution-green-flag` — execution readiness evidence.
- `GET /api/live/reconciliation` — run/read a reconciliation check.
- `POST /api/live/reconcile` — explicitly run reconciliation.
- `GET /api/live/readiness` — combined strategy + execution readiness.

## Live enablement

Passing the Execution Green Flag does not itself enable real-money trading. The live runner still requires the existing strategy Green Flag, allowed account mode, manual approval where configured, risk/volume limits, the unlock phrase, clean reconciliation, and `allow_live_trading=true`.
