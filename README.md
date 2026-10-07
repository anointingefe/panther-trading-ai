# PANTHER Trading AI

PANTHER Trading AI is a guarded auto-trading research system. The first build is
demo-first: it can generate signals, simulate execution, and expose the same
interfaces we will later use for MetaTrader 5 or other broker adapters.

## What v0.1 Does

- Collects market candles through a broker abstraction.
- Runs a simple sentiment collector abstraction for internet/X/news signals.
- Scores trade ideas with technical and sentiment inputs.
- Enforces strict risk gates before any order can be created.
- Executes through a simulation broker by default.
- Keeps the MT5 adapter isolated and disabled unless explicitly configured.

## Safety Defaults

- Live trading is disabled by default.
- The included config uses a paper broker.
- Risk controls block oversized positions, excessive daily loss, and low
  confidence ideas.
- The MT5 adapter raises clear setup errors if MetaTrader 5 is unavailable.

## Quick Start

```bash
cd panther-trading-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m panther_trading.cli run-once --config config/demo.yaml
```

## Dashboard Preview

Run the local dashboard server:

```bash
python3 -m panther_trading.api.server --port 8080
```

Then open `http://127.0.0.1:8080`.

The dashboard includes a market selector and can request fresh paper-trading
snapshots from:

- `GET /api/markets`
- `GET /api/snapshot?symbol=XAUUSD`

The bundled market universe covers common MT5-style forex pairs, metals,
energies, indices, crypto, and major stock CFDs. Broker-specific symbols still
need to be discovered from the connected MT5 account because every broker names
and exposes instruments differently.

## Broker Mode

PANTHER defaults to the safe simulator:

```bash
PANTHER_BROKER=simulated python3 -m panther_trading.api.server --port 8080
```

When MT5 is installed and already logged in on the trading machine, switch the
broker adapter explicitly:

```bash
PANTHER_BROKER=mt5 python3 -m panther_trading.api.server --port 8080
```

The dashboard exposes broker health at:

- `GET /api/broker/status`

Live trading remains blocked by config unless `execution.allow_live_trading` is
changed deliberately. Keep demo mode until the strategy journal proves itself.

The dashboard includes a Demo / Live execution toggle. The Live side is a
guarded control: it stays locked unless backend config explicitly enables live
trading. This prevents the UI from becoming a one-click live-trade switch.

## Live Trading Guard

PANTHER includes the live-trading control path, but it is inactive by default.
The live guard checks all of these before it can arm:

- `execution.allow_live_trading` must be `true`.
- The active broker must be MetaTrader 5.
- The broker must be connected.
- The account mode must be in `execution.allowed_live_account_modes`.
- The journaled signal must already be manually approved.
- Requested volume must not exceed `execution.max_live_volume`.
- The configured `execution.live_unlock_phrase` must be provided.

Current readiness can be inspected at:

- `GET /api/live/readiness`

The arming endpoint exists for future controlled rollout:

- `POST /api/live/arm`

This endpoint does not place a trade. It only verifies whether live execution
would be allowed under the current safety rules.

## Strategy Research Lab

PANTHER now includes a research layer that evaluates candidate strategies before
they can be trusted. The lab runs rolling simulated tests across recent candles
and grades each strategy by:

- number of trades tested
- win rate
- net R
- average R
- profit factor
- max drawdown
- average confidence
- approval status

The dashboard shows the current market condition, approved/watch counts, the
best-ranked strategy, and scorecards explaining why each strategy is approved,
watched, incubating, or rejected.

Research output is available at:

- `GET /api/research/strategies?symbol=EURUSD`

## Strategy Trust Gate

Research is now wired into execution safety. A normal signal must pass both:

- risk rules
- strategy research trust rules

If the research lab has no approved strategy for the selected market condition,
PANTHER blocks the order and records the journal entry as non-approvable. This
means a weak or unproven strategy cannot become a paper trade just because the
latest signal looks confident.

## Project Layout

```text
panther_trading/
  brokers/        Broker adapters: simulation now, MT5 later
  data/           Market and sentiment collection interfaces
  execution/      Trade execution orchestration
  risk/           Risk controls and order gates
  strategies/     Strategy engines and signal scoring
  backtesting/    Historical simulation tools
  api/            Future dashboard API
```

## Next Milestones

1. Connect a real MT5 demo account on Windows/VPS.
2. Add economic calendar/news ingestion.
3. Add X API ingestion with strict spend limits.
4. Build a dashboard with logs, signals, and manual approval.
5. Backtest strategies before allowing semi-auto execution.
