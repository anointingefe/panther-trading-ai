# PANTHER Trading AI

PANTHER Trading AI is a guarded auto-trading research system. The first build is
demo-first: it can generate signals, simulate execution, and expose the same
interfaces we will later use for MetaTrader 5 or other broker adapters.

The project follows the [PANTHER Precision Standard](docs/PRECISION_STANDARD.md):
every trade path must be measurable, explainable, journaled, and blocked when
the evidence is weak.

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
- Manual approvals cannot bypass the demo position cap or the one-position-per-symbol cap.
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
- `GET /api/market/structure?symbol=XAUUSD&timeframe=M5&count=160`
- `GET /api/learning?symbol=XAUUSD`
- `GET /api/intelligence?symbol=XAUUSD`
- `GET /api/exits/review`

The bundled market universe covers common MT5-style forex pairs, metals,
energies, indices, crypto, and major stock CFDs. Broker-specific symbols still
need to be discovered from the connected MT5 account because every broker names
and exposes instruments differently.

### Phone Access On The Same Wi-Fi

The dashboard can be opened from a phone when the laptop and phone are on the
same trusted Wi-Fi network. Start the server on all local interfaces:

```bash
PANTHER_BROKER=mt5 python3 -m panther_trading.api.server --host 0.0.0.0 --port 8090
```

On Windows PowerShell:

```powershell
$env:PANTHER_BROKER="mt5"
python -m panther_trading.api.server --host 0.0.0.0 --port 8090
```

Find the laptop's local IPv4 address with `ipconfig`, then open this on the
phone browser:

```text
http://YOUR-LAPTOP-IP:8090
```

Do not expose this local server directly to the public internet. It is designed
for trusted local-network demo control while the live gate remains locked.

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

Closed MT5 demo history can be synced into the validation ledger from:

- `POST /api/mt5/sync-history`

The sync imports only PANTHER-tagged closed MT5 trades with enough metadata to
calculate honest R-multiples. Trades without a usable stop-loss are skipped
because they cannot prove risk-adjusted edge.

Live trading remains blocked by config unless `execution.allow_live_trading` is
changed deliberately. Keep demo mode until the strategy journal proves itself.

The dashboard includes a Demo / Live execution toggle. The Live side is a
guarded control: it stays locked unless backend config explicitly enables live
trading. This prevents the UI from becoming a one-click live-trade switch.

## Demo Auto Runner

PANTHER now includes a guarded MT5 demo proving engine. It is separate from the
live guard and refuses real account mode. The runner scans a capped set of MT5
markets, applies the strategy and risk rules, prevents duplicate symbol
exposure, and can place tiny demo-only incubation orders with stop-loss and
take-profit attached.

The demo runner now has its own proving limits:

- `demo_auto.max_symbols_per_cycle: 96`
- `demo_auto.max_orders_per_cycle: 12`
- `demo_auto.max_open_positions: 12`
- `demo_auto.max_positions_per_symbol: 1`

The core risk cap remains separate for manual/live pathways. This lets demo
testing collect more evidence across different markets without loosening live
execution safety.

The dashboard shows those demo limits directly in the MT5 Auto Runner card, so
the operator can see whether the system is blocked by confidence, broker
permissions, per-cycle capacity, or the total open-position cap.

After a closed demo loss, the runner blocks that symbol for a configurable
cooldown window and refuses repeated symbol losses from becoming revenge
trades. It also skips entries when the latest candle range is an abnormal
volatility spike, and it can match broker suffixes such as `XAUUSDm` back to
the intended market.

The demo runner also uses the useful parts of the temporal-bias/Kelly/Bayesian
framework seen in public AI-trading posts, but in a conservative form:

- Temporal edge blocks a symbol-hour once enough closed demo history shows the
  window is weak.
- Bayesian updates blend the raw signal confidence with actual closed demo
  outcomes for that symbol.
- Kelly sizing can reduce demo order volume when edge is weak, but it never
  increases above the configured demo cap.

Dashboard controls:

- `Run Demo Cycle` runs one guarded scan-and-place cycle.
- `Start Loop` repeats the demo cycle every configured interval.
- `Stop Demo Loop` stops the local background loop.

API controls:

- `GET /api/demo-auto/status`
- `POST /api/demo-auto/cycle`
- `POST /api/demo-auto/start`
- `POST /api/demo-auto/stop`

CLI:

```bash
PANTHER_BROKER=mt5 python -m panther_trading.cli demo-auto-cycle --config config/demo.yaml
```

### Windows Pull-and-Run

PowerShell can update and start the system in one command. From the repository
folder, run:

```powershell
.\scripts\Start-Panther.ps1 -Broker mt5 -StartDemoLoop
```

That fetches the latest `main`, fast-forwards the working tree, creates the
Python virtual environment if needed, installs requirements, starts the API,
checks `/api/health`, and starts the guarded demo loop. Use `-NoPull` when
working offline. The script does not unlock live trading.

To start it automatically when Windows logs in, run PowerShell once as the
user account that should own the process:

```powershell
.\scripts\Install-PantherStartup.ps1 -Broker mt5
```

This is laptop auto-start, not public cloud hosting. MetaTrader 5 must be
installed, logged in to the intended demo account, and allowed to trade. The
dashboard will honestly show a blocked or simulated state when that connection
is unavailable.

This is still demo only. It exists to create broker-auditable evidence for the
edge-validation gate, not to bypass live trading safety.

## Exit Intelligence

Every PANTHER entry is expected to have a defined stop-loss and take-profit.
The exit manager now reviews open demo trades and classifies each one as:

- `close` when stop-loss, take-profit, invalidation, or max trade time is hit
- `move_to_breakeven` after the position reaches the configured R threshold
- `trail_stop` after stronger profit movement justifies protecting structure
- `hold` while the original thesis remains valid

Dashboard controls expose the current exit plan and can apply demo close
decisions to local paper positions:

- `GET /api/exits/review`
- `POST /api/exits/apply`

The MT5 adapter now has PANTHER-tagged open-position discovery and close-order
support, but live execution remains behind the existing guard rails.

## Live Trading Guard

PANTHER includes the live-trading control path, but it is inactive by default.
The live guard checks all of these before it can arm:

- `execution.allow_live_trading` must be `true`.
- The active broker must be MetaTrader 5.
- The broker must be connected.
- The account mode must be in `execution.allowed_live_account_modes`.
- The journaled signal must already be manually approved.
- Requested volume must not exceed `execution.max_live_volume`.
- The demo edge-validation gate must pass its minimum history, performance, and
  drawdown thresholds.
- The configured `execution.live_unlock_phrase` must be provided.

Current readiness can be inspected at:

- `GET /api/live/readiness`
- `GET /api/validation/edge`

The arming endpoint exists for future controlled rollout:

- `POST /api/live/arm`

This endpoint does not place a trade. It only verifies whether live execution
would be allowed under the current safety rules.

The live runner scaffold also exists now and can be inspected at:

- `GET /api/live-auto/status`

It is built for a future controlled rollout, but it remains locked unless the
live guard passes every condition: MT5 connection, allowed account mode, approved
signal, volume cap, demo edge validation, and unlock phrase.

## Demo Edge Validation

The live gate now requires evidence from closed demo positions. The default
thresholds in `config/demo.yaml` are 30 closed trades across 14 separate trading
days, profit factor of at least 1.2, net result of at least 5R, win rate of at
least 35%, and maximum drawdown no greater than 6R. Costs and results are
measured in R using each position's entry-to-stop distance. Until every
threshold passes, the dashboard reports the exact missing conditions and live
readiness remains locked.

The paper execution path also enforces a maximum of three open positions and
one open position per symbol. These limits apply to manual approvals as well as
automated signal generation.

## Strategy Research Lab

PANTHER now includes a research layer that evaluates candidate strategies before
they can be trusted. The lab runs rolling simulated tests across recent candles
and grades each strategy by:

- number of trades tested
- win rate
- gross net R
- net R after spread and slippage assumptions
- average R
- profit factor
- max drawdown
- recent out-of-sample net R
- precision grade
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

## Learning And Evolution

PANTHER now includes an evolution control layer. It does not blindly mutate the
bot while money is at risk. Instead, it reads:

- current research scorecards
- closed demo trade outcomes
- journaled signal decisions
- broker-backed market scans

The learning report shows whether the system is still observing, actively
building demo evidence, or ready to promote a strategy. Promotion requires both
approved research and enough closed demo trades. Until that proof exists, the
engine can recommend adaptations, but live trading stays locked.

Every closed demo loss is also reviewed. The dashboard surfaces the latest loss
in R-multiple terms, tracks the loss streak, and records conservative actions
such as no size increase, no revenge trade, and more confirmation before trust
can rise.

## Market Intelligence

PANTHER now has a public market-intelligence collector. It reads public RSS/web
feeds when reachable, maps stories to symbols such as gold, BTC, oil, indices,
and major FX pairs, then turns the language into a cautious sentiment score used
by the dashboard signal. If feeds are unreachable, the collector falls back to a
neutral report instead of inventing evidence.

X is not silently scraped. Add X through an official API, approved connector, or
user-provided post links so the system stays reliable, lawful, and auditable.

## AI Trader Toolkit

The dashboard now includes the practical tools from the reviewed trading prompt
screenshots:

- Daily opportunity scanner: ranks the strongest moving markets for the next session.
- Smart journal inputs: closed trade outcomes keep feeding the learning engine.
- Real-time risk analyzer: estimates open risk and 10% shock exposure.
- Custom strategy builder: shows the exact proof required before promotion.
- News-to-trades translator: turns public market intelligence into filtered trade ideas.
- Strategy backtester: keeps research scorecards before strategy trust.
- Position sizing manager: sizes from capital, stop distance, risk cap, and loss streak.
- Market-trap detector: gives reasons not to enter and what must change first.

This layer is designed to make PANTHER smarter, but not reckless. It can reduce
or block risk after bad evidence; it cannot auto-increase live risk without the
live guard, demo proof, and explicit operator approval.

## Candle Intelligence

PANTHER includes a candle intelligence layer inspired by the reviewed candle-box
video. It reads a higher-timeframe candle as the box and lower-timeframe candles
as the execution evidence.

The current report includes:

- previous daily high, low, and midpoint
- latest lower-timeframe position inside the box
- EMA bias
- VWAP bias
- candle patterns such as momentum, engulfing, doji, rejection wick, and inside bar
- bullish, bearish, or wait confirmation

Implementation notes are captured in
[VIDEO_REVIEW_2026-10-07.md](docs/VIDEO_REVIEW_2026-10-07.md).

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
2. Run MT5 demo-history sync until the edge-validation gate has real closed
   trades to evaluate.
3. Add economic calendar/news ingestion.
4. Add X API ingestion with strict spend limits.
5. Add MT5 stop-modification support for breakeven/trailing decisions.
6. Backtest strategies before allowing semi-auto execution.
