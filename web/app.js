const fallbackSnapshot = {
  mode: "Paper",
  systemStatus: "Risk Guard Active",
  executionMode: {
    active: "demo",
    liveEnabled: false,
    liveLockedReason: "Live trading is locked in backend config. Demo mode only."
  },
  liveReadiness: {
    enabled: false,
    armed: false,
    reasons: ["Backend config has allow_live_trading=false."],
    checklist: [
      "Live trading must be enabled in backend config.",
      "Broker must be connected through the MT5 adapter.",
      "Manual approval must exist for the exact signal."
    ]
  },
  research: {
    marketCondition: "range",
    summary: {
      approved: 0,
      watch: 0,
      rejected: 0,
      bestStrategy: "Waiting",
      bestNetR: 0
    },
    scorecards: []
  },
  symbol: "EURUSD",
  latestClose: 1.08065,
  signal: {
    side: "sell",
    confidence: 0.2538,
    entry: 1.08065,
    stop_loss: 1.08305,
    take_profit: 1.07705,
    rationale: [
      "Fast SMA is below slow SMA, showing short-term weakness.",
      "Sentiment is not strong enough to override the technical sell bias.",
      "Risk guard blocked execution because confidence is below threshold."
    ]
  },
  order: {
    status: "rejected",
    message: "Signal confidence is below minimum"
  },
  strategyGate: {
    allowed: false,
    status: "blocked",
    reason: "No strategy is approved by the research lab for this market condition.",
    selectedStrategy: null
  },
  candleIntelligence: {
    box: {
      timeframe: "D1",
      high: 1.09,
      low: 1.07,
      midpoint: 1.08,
      latest_position: "inside_box",
      inside_box: true
    },
    lower_timeframe: "M5",
    ema_bias: "neutral",
    vwap_bias: "neutral",
    confirmation: "wait",
    confirmation_score: 0,
    patterns: [],
    notes: []
  },
  marketStructure: {
    symbol: "EURUSD",
    timeframe: "M15",
    source: "fallback",
    latest: 1.08065,
    high: 1.091,
    low: 1.071,
    range: 0.02,
    change: 0,
    closes: [1.081, 1.083, 1.08, 1.085, 1.084, 1.088, 1.086, 1.09, 1.087, 1.08065]
  },
  edgeValidation: {
    status: "insufficient_data",
    passed: false,
    reasons: ["Needs at least 30 closed demo trades."],
    closed_trades: 0,
    trading_days: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    gross_profit_r: 0,
    gross_loss_r: 0,
    profit_factor: 0,
    net_r: 0,
    max_drawdown_r: 0
  },
  learning: {
    status: "learning",
    phase: "observation",
    sample_size: 0,
    promoted_strategy: null,
    confidence: 0,
    score: 0,
    adaptations: [
      "Keep live trading locked while the demo evidence set grows.",
      "Re-rank strategies after each fresh market scan and synced MT5 history batch."
    ],
    blockers: ["Needs at least 30 closed demo trades before promotion."],
    loss_review: {
      losses: 0,
      latestSymbol: null,
      latestR: 0,
      consecutiveLosses: 0,
      assessment: "No closed demo losses recorded yet.",
      actions: ["Keep collecting demo outcomes before changing strategy trust."]
    },
    policy: "PANTHER may rank and recommend strategy changes, but it cannot auto-promote a strategy without enough closed demo trades and passing research evidence."
  },
  exitReview: {
    reviewed: 0,
    actions: { close: 0, protect: 0, hold: 0 },
    decisions: [],
    policy: "Every trade is reviewed for SL/TP touch, thesis invalidation, time stop, breakeven, and trailing protection."
  },
  marketIntelligence: {
    symbol: "EURUSD",
    score: 0,
    confidence: 0,
    sources: ["market-intelligence-fallback"],
    items: [
      {
        title: "No fresh public feed items matched EURUSD; trade only from price action and demo proof.",
        source: "market-intelligence-fallback",
        url: "",
        polarity: 0,
        weight: 0.25,
        symbols: ["EURUSD"]
      }
    ],
    errors: [],
    policy: "Uses public RSS/web sources when available. X content should be connected through an official API or user-provided links; private or logged-in feeds are not silently scraped."
  },
  demoAuto: {
    running: false,
    lastCycle: null,
    message: "Demo auto runner has not run yet."
  },
  journalEntry: null,
  sentiment: {
    score: 0.12,
    confidence: 0.55,
    sources: ["static-dev-sentiment"]
  },
  broker: {
    name: "PANTHER Simulated Broker",
    connected: true,
    mode: "paper",
    account_login: "SIM-0001",
    account_server: "local-simulator",
    balance: 10000,
    equity: 10000,
    open_positions: 0,
    symbols_total: 48,
    message: "Safe paper broker active",
    symbols_sample: []
  },
  positions: [],
  metrics: {
    equity: 10000,
    dailyPnl: 0,
    winRate: 0,
    riskUsed: 0
  },
  watchlist: [
    { symbol: "EURUSD", name: "Euro / US Dollar", group: "Forex Majors", bias: "SELL", confidence: 0.25 },
    { symbol: "GBPUSD", name: "British Pound / US Dollar", group: "Forex Majors", bias: "WAIT", confidence: 0.41 },
    { symbol: "XAUUSD", name: "Gold Spot / US Dollar", group: "Metals", bias: "WATCH", confidence: 0.58 },
    { symbol: "NAS100", name: "Nasdaq 100", group: "Indices", bias: "WAIT", confidence: 0.36 }
  ],
  markets: [
    { symbol: "EURUSD", name: "Euro / US Dollar", group: "Forex Majors" },
    { symbol: "GBPUSD", name: "British Pound / US Dollar", group: "Forex Majors" },
    { symbol: "XAUUSD", name: "Gold Spot / US Dollar", group: "Metals" },
    { symbol: "NAS100", name: "Nasdaq 100", group: "Indices" },
    { symbol: "BTCUSD", name: "Bitcoin / US Dollar", group: "Crypto" }
  ],
  activity: [
    "Collected latest market candles",
    "Blended technical and sentiment score",
    "Risk decision: Signal confidence is below minimum"
  ]
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0
});

const pct = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 0
});

let currentJournalEntry = null;

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function setLoading(isLoading) {
  const button = document.getElementById("run-scan");
  button.disabled = isLoading;
  button.textContent = isLoading ? "Scanning..." : "Run Scan";
}

async function readJsonResponse(response, fallbackMessage) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await response.text();
    const hint = text.trim().startsWith("<")
      ? "Backend route returned HTML. Restart the server after pulling the latest code."
      : text.slice(0, 160);
    throw new Error(hint || fallbackMessage);
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || fallbackMessage);
  }
  return payload;
}

function renderDashboard(data) {
  setText("signal-symbol", data.symbol);
  setText("mode-pill", data.mode);
  setText("signal-side", data.signal.side.toUpperCase());
  setText("confidence", pct.format(data.signal.confidence));
  setText("entry", data.signal.entry.toFixed(5));
  setText("stop-loss", data.signal.stop_loss.toFixed(5));
  setText("take-profit", data.signal.take_profit.toFixed(5));
  setText("risk-banner", `${data.order.status.toUpperCase()}: ${data.order.message}`);
  renderStrategyGate(data.strategyGate || fallbackSnapshot.strategyGate);
  setText("equity", money.format(data.metrics.equity));
  setText("daily-pnl", money.format(data.metrics.dailyPnl));
  setText("risk-used", pct.format(data.metrics.riskUsed));
  setText("win-rate", pct.format(data.metrics.winRate));
  renderBroker(data.broker || fallbackSnapshot.broker);
  renderExecutionMode(data.executionMode || fallbackSnapshot.executionMode);
  renderLiveReadiness(data.liveReadiness || fallbackSnapshot.liveReadiness);
  renderDemoAuto(data.demoAuto || fallbackSnapshot.demoAuto);
  renderApproval(data.journalEntry || null);
  renderPositions(data.positions || []);
  renderEdgeValidation(data.edgeValidation || fallbackSnapshot.edgeValidation);
  renderLearning(data.learning || fallbackSnapshot.learning);
  renderExitReview(data.exitReview || fallbackSnapshot.exitReview);
  renderMarketIntelligence(data.marketIntelligence || fallbackSnapshot.marketIntelligence);
  renderResearch(data.research || fallbackSnapshot.research);
  renderCandleIntelligence(data.candleIntelligence || fallbackSnapshot.candleIntelligence);
  renderMarketStructure(data.marketStructure || fallbackSnapshot.marketStructure);

  const watchlist = document.getElementById("watchlist");
  watchlist.innerHTML = data.watchlist
    .map(
      (item) => `
        <div class="watch-row">
          <strong>${item.symbol}</strong>
          <span title="${item.name || item.symbol}">${item.bias}</span>
          <span>${pct.format(item.confidence)}</span>
        </div>
      `
    )
    .join("");

  const rationale = document.getElementById("rationale");
  rationale.innerHTML = data.signal.rationale.map((item) => `<li>${item}</li>`).join("");

  const activity = document.getElementById("activity");
  activity.innerHTML = data.activity.map((item) => `<li>${item}</li>`).join("");

  renderMarketUniverse(data.markets || []);
}

function formatPrice(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1000) {
    return number.toFixed(2);
  }
  if (Math.abs(number) >= 10) {
    return number.toFixed(3);
  }
  return number.toFixed(5);
}

function renderMarketStructure(structure) {
  const closes = (structure.closes || []).map(Number).filter((value) => Number.isFinite(value));
  setText("structure-symbol", `${structure.symbol || "Market"} Structure`);
  setText("structure-source", `${structure.timeframe || "M15"} / ${String(structure.source || "data").toUpperCase()}`);
  setText("structure-latest", formatPrice(structure.latest));
  setText("structure-high", formatPrice(structure.high));
  setText("structure-low", formatPrice(structure.low));
  setText("structure-range", formatPrice(structure.range));

  const line = document.getElementById("structure-line");
  if (!closes.length) {
    line.setAttribute("points", "");
    return;
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = Math.max(max - min, Number.EPSILON);
  const points = closes
    .map((close, index) => {
      const x = closes.length === 1 ? 50 : (index / (closes.length - 1)) * 100;
      const y = 88 - ((close - min) / span) * 76;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  line.setAttribute("points", points);
}

function renderEdgeValidation(report) {
  setText("edge-status", String(report.status || "waiting").replaceAll("_", " ").toUpperCase());
  setText("edge-trades", String(report.closed_trades || 0));
  setText("edge-net-r", Number(report.net_r || 0).toFixed(2));
  setText("edge-profit-factor", Number(report.profit_factor || 0).toFixed(2));
  setText("edge-drawdown", `${Number(report.max_drawdown_r || 0).toFixed(2)}R`);

  const reasons = report.reasons || [];
  document.getElementById("edge-reasons").innerHTML = reasons.length
    ? reasons.map((reason) => `<li class="blocked">${reason}</li>`).join("")
    : `<li>Demo edge validation has passed.</li>`;
}

function renderLearning(report) {
  setText("learning-status", String(report.status || "learning").replaceAll("_", " ").toUpperCase());
  setText("learning-phase", String(report.phase || "observation").replaceAll("_", " ").toUpperCase());
  setText("learning-sample", String(report.sample_size || 0));
  setText("learning-confidence", pct.format(report.confidence || 0));
  setText("learning-strategy", report.promoted_strategy || "Incubating");
  setText("learning-policy", report.policy || fallbackSnapshot.learning.policy);
  const loss = report.loss_review || fallbackSnapshot.learning.loss_review;
  const lossSymbol = loss.latestSymbol ? `${loss.latestSymbol} ` : "";
  setText(
    "learning-loss",
    `${lossSymbol}${Number(loss.latestR || 0).toFixed(2)}R / ${loss.consecutiveLosses || 0} loss streak`
  );
  setText("learning-loss-assessment", loss.assessment || fallbackSnapshot.learning.loss_review.assessment);

  const adaptations = report.adaptations || [];
  const blockers = report.blockers || [];
  document.getElementById("learning-list").innerHTML = [
    ...adaptations.map((item) => `<li>${item}</li>`),
    ...blockers.map((item) => `<li class="blocked">${item}</li>`),
    ...(loss.actions || []).map((item) => `<li>${item}</li>`)
  ].join("");
}

function renderDemoAuto(state) {
  const running = Boolean(state.running);
  const lastCycle = state.lastCycle || null;
  setText("demo-auto-status", running ? "RUNNING" : lastCycle ? String(lastCycle.status || "idle").toUpperCase() : "IDLE");
  setText("demo-auto-message", state.message || "Demo auto runner ready.");
  const list = document.getElementById("demo-auto-list");
  if (!lastCycle) {
    list.innerHTML = `<p class="empty-state">No demo auto cycle has run yet.</p>`;
    return;
  }
  const decisions = lastCycle.decisions || [];
  if (!decisions.length) {
    list.innerHTML = `<p class="empty-state">${(lastCycle.reasons || ["No scanned markets."])[0]}</p>`;
    return;
  }
  list.innerHTML = decisions
    .slice(0, 6)
    .map(
      (decision) => `
        <div class="journal-row">
          <div>
            <strong>${decision.symbol} ${String(decision.side).toUpperCase()}</strong>
            <small>${decision.reason}</small>
          </div>
          <span>${decision.action}</span>
          <small>${pct.format(decision.confidence || 0)}</small>
        </div>
      `
    )
    .join("");
}

function renderExitReview(report) {
  const actions = report.actions || fallbackSnapshot.exitReview.actions;
  setText("exit-status", report.reviewed ? "ACTIVE" : "CLEAR");
  setText("exit-policy", report.policy || fallbackSnapshot.exitReview.policy);
  setText("exit-close", String(actions.close || 0));
  setText("exit-protect", String(actions.protect || 0));
  setText("exit-hold", String(actions.hold || 0));

  const list = document.getElementById("exit-list");
  const decisions = report.decisions || [];
  if (!decisions.length) {
    list.innerHTML = `<p class="empty-state">No open trades need exit action right now.</p>`;
    return;
  }

  list.innerHTML = decisions
    .slice(0, 6)
    .map(
      (decision) => `
        <div class="exit-row ${decision.action}">
          <div>
            <strong>${decision.symbol} ${String(decision.side).toUpperCase()}</strong>
            <small>${decision.reason}</small>
          </div>
          <span>${String(decision.action).replaceAll("_", " ")}</span>
          <small>${Number(decision.r_multiple || 0).toFixed(2)}R</small>
        </div>
      `
    )
    .join("");
}

function renderMarketIntelligence(report) {
  const score = Number(report.score || 0);
  setText("intel-score", `${score >= 0 ? "+" : ""}${Math.round(score * 100)}%`);
  setText("intel-policy", report.policy || fallbackSnapshot.marketIntelligence.policy);
  const list = document.getElementById("intel-list");
  const items = report.items || [];
  if (!items.length) {
    list.innerHTML = `<p class="empty-state">No public intelligence items available.</p>`;
    return;
  }
  list.innerHTML = items
    .slice(0, 5)
    .map((item) => {
      const polarity = Number(item.polarity || 0);
      const label = polarity > 0.15 ? "bullish" : polarity < -0.15 ? "bearish" : "neutral";
      const title = item.url ? `<a href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a>` : item.title;
      return `
        <div class="intel-row ${label}">
          <div>
            <strong>${title}</strong>
            <small>${item.source} / ${(item.symbols || []).join(", ")}</small>
          </div>
          <span>${label}</span>
        </div>
      `;
    })
    .join("");
}

function renderCandleIntelligence(report) {
  const box = report.box || fallbackSnapshot.candleIntelligence.box;
  setText("candle-confirmation", `${String(report.confirmation || "wait").toUpperCase()} ${pct.format(report.confirmation_score || 0)}`);
  setText("candle-box-high", Number(box.high).toFixed(5));
  setText("candle-box-mid", Number(box.midpoint).toFixed(5));
  setText("candle-box-low", Number(box.low).toFixed(5));

  const patterns = report.patterns || [];
  const notes = report.notes || [];
  const patternList = document.getElementById("pattern-list");
  if (!patterns.length && !notes.length) {
    patternList.innerHTML = `<p class="empty-state">No candle intelligence yet.</p>`;
    return;
  }

  patternList.innerHTML = [
    ...patterns.slice(0, 4).map(
      (pattern) => `
        <div class="pattern-row">
          <strong>${pattern.name.replaceAll("_", " ")}</strong>
          <span>${pattern.direction} / ${pct.format(pattern.strength || 0)}</span>
        </div>
      `
    ),
    ...notes.slice(0, 3).map((note) => `<p class="candle-note">${note}</p>`)
  ].join("");
}

function renderStrategyGate(gate) {
  const banner = document.getElementById("strategy-banner");
  const selected = gate.selectedStrategy ? ` Selected: ${gate.selectedStrategy}.` : "";
  banner.textContent = `${gate.status.toUpperCase()}: ${gate.reason}${selected}`;
  banner.classList.toggle("approved", Boolean(gate.allowed));
}

function renderResearch(research) {
  const summary = research.summary || fallbackSnapshot.research.summary;
  setText("research-condition", (research.marketCondition || "unknown").toUpperCase());
  setText("research-approved", String(summary.approved || 0));
  setText("research-watch", String(summary.watch || 0));
  setText("research-best", summary.bestStrategy || "Waiting");

  const list = document.getElementById("strategy-list");
  const scorecards = research.scorecards || [];
  if (!scorecards.length) {
    list.innerHTML = `<p class="empty-state">No strategy research has run yet.</p>`;
    return;
  }

  list.innerHTML = scorecards
    .map(
      (card) => `
        <div class="strategy-card ${card.status}">
          <div class="strategy-card-head">
            <div>
              <strong>${card.name}</strong>
              <span>${card.description}</span>
            </div>
            <b>${card.status.toUpperCase()}</b>
          </div>
          <div class="strategy-metrics">
            <span>Trades <strong>${card.trades}</strong></span>
            <span>Win <strong>${pct.format(card.win_rate)}</strong></span>
            <span>PF <strong>${Number(card.profit_factor).toFixed(2)}</strong></span>
            <span>Net R <strong>${Number(card.net_r).toFixed(2)}</strong></span>
            <span>OOS <strong>${Number(card.out_of_sample_net_r).toFixed(2)}R</strong></span>
            <span>Grade <strong>${String(card.precision_grade || "n/a").replaceAll("_", " ")}</strong></span>
          </div>
          <ul>
            ${(card.notes || []).map((note) => `<li>${note}</li>`).join("")}
          </ul>
        </div>
      `
    )
    .join("");
}

function renderLiveReadiness(readiness) {
  const status = readiness.armed ? "Armed" : readiness.enabled ? "Enabled" : "Locked";
  setText("live-readiness-status", status.toUpperCase());
  const reasons = readiness.reasons || [];
  const checklist = readiness.checklist || [];
  const copy = reasons.length
    ? `Live execution is inactive: ${reasons[0]}`
    : "Live execution checks passed, but final trade placement still requires an approved signal.";
  setText("live-readiness-copy", copy);

  document.getElementById("live-readiness-list").innerHTML = checklist
    .map((item) => `<li>${item}</li>`)
    .join("") +
    reasons
      .map((reason) => `<li class="blocked">Blocked: ${reason}</li>`)
    .join("");
}

function renderApproval(entry) {
  currentJournalEntry = entry;
  const status = entry?.approval_status || "waiting";
  setText("approval-status", status.replaceAll("_", " ").toUpperCase());
  const approveButton = document.getElementById("approve-signal");
  const rejectButton = document.getElementById("reject-signal");
  const canDecide = entry && entry.approval_status === "pending_approval";

  approveButton.disabled = !canDecide;
  rejectButton.disabled = !entry || ["approved", "rejected"].includes(entry.approval_status);

  if (!entry) {
    setText("approval-copy", "Run a scan to create a journaled signal before any demo trade decision.");
    return;
  }

  if (entry.approval_status === "blocked_by_risk") {
    setText("approval-copy", `${entry.symbol} ${entry.side.toUpperCase()} was blocked by risk: ${entry.order_message}`);
    return;
  }

  setText(
    "approval-copy",
    `${entry.symbol} ${entry.side.toUpperCase()} at ${entry.entry.toFixed(5)} with ${pct.format(entry.confidence)} confidence. Approval opens a protected demo trade.`
  );
}

async function submitDecision(decision) {
  if (!currentJournalEntry) {
    return;
  }

  const response = await fetch("/api/journal/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: currentJournalEntry.id,
      decision,
      note: `${decision} from dashboard`
    })
  });
  const payload = await response.json();
  if (!response.ok) {
    setText("approval-copy", payload.error || "Decision failed");
    return;
  }
  renderApproval(payload.entry);
  await refreshPositions();
  await refreshJournal();
}

async function stopPosition(positionId, reason = "manual_stop") {
  const response = await fetch("/api/positions/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: positionId, reason })
  });
  const payload = await response.json();
  if (!response.ok) {
    setText("approval-copy", payload.error || "Stop trade failed");
    return;
  }
  await refreshPositions();
}

async function emergencyStopPositions() {
  const response = await fetch("/api/positions/close-all", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "emergency_stop" })
  });
  if (response.ok) {
    await refreshPositions();
  }
}

async function syncMt5History() {
  const button = document.getElementById("sync-mt5-history");
  const status = document.getElementById("sync-mt5-status");
  button.disabled = true;
  status.textContent = "Checking MT5 history...";
  try {
    const response = await fetch("/api/mt5/sync-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: 30 })
    });
    const payload = await readJsonResponse(response, "MT5 history sync failed");
    renderEdgeValidation(payload.edgeValidation || fallbackSnapshot.edgeValidation);
    await refreshPositions();
    status.textContent = `${payload.imported || 0} verified closed MT5 trades imported.`;
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "MT5 history sync failed";
  } finally {
    button.disabled = false;
  }
}

async function demoAutoAction(action) {
  const endpoint = `/api/demo-auto/${action}`;
  setText("demo-auto-message", action === "cycle" ? "Running one guarded demo cycle..." : "Updating demo loop...");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const payload = await readJsonResponse(response, "Demo auto action failed");
    renderDemoAuto(payload.demoAuto || fallbackSnapshot.demoAuto);
    await refreshPositions();
  } catch (error) {
    setText("demo-auto-message", error instanceof Error ? error.message : "Demo auto action failed");
  }
}

async function refreshDemoAuto() {
  try {
    const response = await fetch("/api/demo-auto/status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderDemoAuto(payload.demoAuto || fallbackSnapshot.demoAuto);
  } catch {
    renderDemoAuto(fallbackSnapshot.demoAuto);
  }
}

function renderExecutionMode(executionMode) {
  const demoButton = document.getElementById("demo-mode");
  const liveButton = document.getElementById("live-mode");
  const modeBanner = document.getElementById("mode-banner");
  const isLive = executionMode.active === "live";

  demoButton.classList.toggle("active", !isLive);
  liveButton.classList.toggle("active", isLive);
  liveButton.classList.toggle("locked", !executionMode.liveEnabled);
  setText("mode-pill", isLive ? "Live" : "Demo");

  if (isLive && executionMode.liveEnabled) {
    modeBanner.textContent = "Live mode selected. Manual approval and risk guard remain required.";
    modeBanner.className = "mode-banner live";
  } else {
    modeBanner.textContent = executionMode.liveLockedReason || "Demo mode active.";
    modeBanner.className = "mode-banner";
  }
}

function renderBroker(broker) {
  setText("broker-mode", broker.mode.toUpperCase());
  setText("broker-connection", broker.connected ? "Connected" : "Disconnected");
  setText("broker-account", broker.account_login || "Not available");
  setText("broker-server", broker.account_server || broker.name || "Not available");
  setText("broker-symbols", String(broker.symbols_total || 0));
  setText("broker-message", broker.message);
}

async function refreshSnapshot() {
  const selectedSymbol = document.getElementById("market-select").value || fallbackSnapshot.symbol;
  setLoading(true);
  try {
    const response = await fetch(`/api/snapshot?symbol=${encodeURIComponent(selectedSymbol)}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Snapshot request failed: ${response.status}`);
    }
    const data = await response.json();
    renderDashboard(data);
    await refreshJournal();
    await refreshPositions();
  } catch (error) {
    renderDashboard({
      ...fallbackSnapshot,
      activity: [
        "Backend snapshot unavailable, using local fallback data",
        error instanceof Error ? error.message : "Unknown dashboard error",
        ...fallbackSnapshot.activity
      ]
    });
  } finally {
    setLoading(false);
  }
}

async function refreshPositions() {
  try {
    const response = await fetch("/api/positions", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderPositions(payload.positions || []);
    await refreshExitReview();
  } catch {
    renderPositions([]);
  }
}

async function refreshExitReview() {
  try {
    const response = await fetch("/api/exits/review", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderExitReview(payload.exitReview || fallbackSnapshot.exitReview);
  } catch {
    renderExitReview(fallbackSnapshot.exitReview);
  }
}

async function applyExitDecisions() {
  const button = document.getElementById("apply-exits");
  button.disabled = true;
  button.textContent = "Applying...";
  try {
    const response = await fetch("/api/exits/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const payload = await readJsonResponse(response, "Exit decisions failed");
    renderExitReview(payload.exitReview || fallbackSnapshot.exitReview);
    await refreshPositions();
  } catch (error) {
    setText("exit-policy", error instanceof Error ? error.message : "Exit decisions failed");
  } finally {
    button.disabled = false;
    button.textContent = "Apply Demo Exit Decisions";
  }
}

function renderPositions(positions) {
  const list = document.getElementById("positions-list");
  const openPositions = positions.filter((position) => position.status === "open");
  setText("positions-count", `${openPositions.length} open`);

  if (!positions.length) {
    list.innerHTML = `<p class="empty-state">No demo trades opened yet.</p>`;
    return;
  }

  list.innerHTML = positions
    .slice(0, 6)
    .map((position) => {
      const isOpen = position.status === "open";
      return `
        <div class="position-row">
          <div>
            <strong>${position.symbol} ${position.side.toUpperCase()}</strong>
            <span>${position.status}${position.close_reason ? ` - ${position.close_reason.replaceAll("_", " ")}` : ""}</span>
          </div>
          <div>
            <small>Entry</small>
            <b>${Number(position.entry).toFixed(5)}</b>
          </div>
          <div>
            <small>SL / TP</small>
            <b>${Number(position.stop_loss).toFixed(5)} / ${Number(position.take_profit).toFixed(5)}</b>
          </div>
          <button ${isOpen ? "" : "disabled"} type="button" data-stop-position="${position.id}">
            Stop
          </button>
        </div>
      `;
    })
    .join("");
}

async function refreshJournal() {
  try {
    const response = await fetch("/api/journal", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderJournal(payload.entries || []);
  } catch {
    renderJournal([]);
  }
}

function renderJournal(entries) {
  const list = document.getElementById("journal-list");
  if (!entries.length) {
    list.innerHTML = `<p class="empty-state">No journal entries yet.</p>`;
    return;
  }

  list.innerHTML = entries
    .slice(0, 8)
    .map(
      (entry) => `
        <div class="journal-row">
          <strong>${entry.symbol} ${entry.side.toUpperCase()}</strong>
          <span>${entry.approval_status.replaceAll("_", " ")}</span>
          <small>${pct.format(entry.confidence)}</small>
        </div>
      `
    )
    .join("");
}

function renderMarketUniverse(markets) {
  const select = document.getElementById("market-select");
  const current = select.value || fallbackSnapshot.symbol;
  select.innerHTML = markets
    .map((market) => `<option value="${market.symbol}">${market.symbol} - ${market.name}</option>`)
    .join("");
  select.value = markets.some((market) => market.symbol === current) ? current : fallbackSnapshot.symbol;

  const groups = markets.reduce((acc, market) => {
    acc[market.group] ||= [];
    acc[market.group].push(market);
    return acc;
  }, {});

  document.getElementById("market-groups").innerHTML = Object.entries(groups)
    .map(
      ([group, items]) => `
        <section class="market-group">
          <h3>${group}</h3>
          <div>
            ${items.map((item) => `<span title="${item.name}">${item.symbol}</span>`).join("")}
          </div>
        </section>
      `
    )
    .join("");
}

document.getElementById("run-scan").addEventListener("click", refreshSnapshot);
document.getElementById("approve-signal").addEventListener("click", () => submitDecision("approved"));
document.getElementById("reject-signal").addEventListener("click", () => submitDecision("rejected"));
document.getElementById("sync-mt5-history").addEventListener("click", syncMt5History);
document.getElementById("demo-auto-cycle").addEventListener("click", () => demoAutoAction("cycle"));
document.getElementById("demo-auto-start").addEventListener("click", () => demoAutoAction("start"));
document.getElementById("demo-auto-stop").addEventListener("click", () => demoAutoAction("stop"));
document.getElementById("apply-exits").addEventListener("click", applyExitDecisions);
document.getElementById("positions-list").addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("[data-stop-position]");
  if (button) {
    stopPosition(button.dataset.stopPosition);
  }
});
document.getElementById("demo-mode").addEventListener("click", () => {
  renderExecutionMode({ active: "demo", liveEnabled: false, liveLockedReason: "Demo mode active." });
});
document.getElementById("live-mode").addEventListener("click", () => {
  const message = "Live trading is locked by backend config. Keep demo mode until manual approval and journal checks are complete.";
  renderExecutionMode({ active: "demo", liveEnabled: false, liveLockedReason: message });
});
document.getElementById("emergency-stop").addEventListener("click", () => {
  emergencyStopPositions();
  renderDashboard({
    ...fallbackSnapshot,
    order: {
      status: "rejected",
      message: "Emergency stop engaged. All live execution remains locked."
    },
    activity: ["Emergency stop engaged locally", ...fallbackSnapshot.activity]
  });
});

renderDashboard(fallbackSnapshot);
refreshSnapshot();
refreshJournal();
refreshDemoAuto();
setInterval(refreshDemoAuto, 15000);
