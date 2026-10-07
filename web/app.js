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
  renderApproval(data.journalEntry || null);
  renderPositions(data.positions || []);
  renderResearch(data.research || fallbackSnapshot.research);

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
  } catch {
    renderPositions([]);
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
