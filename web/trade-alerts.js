(() => {
  const panel = document.getElementById('trade-alert-panel');
  const toggle = document.getElementById('trade-alert-toggle');
  const status = document.getElementById('trade-alert-status');
  const history = document.getElementById('trade-alert-history');
  const toasts = document.getElementById('trade-toasts');
  const desktop = document.getElementById('trade-desktop-enable');
  let scope = null, cursor = null, state = null, unread = 0, busy = false;
  let desktopEnabled = false;
  const storageKey = value => `panther-trade-events-v1:${value}`;
  function load(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
  }
  function save() {
    try { localStorage.setItem(storageKey(scope), JSON.stringify(state)); } catch { /* In-memory deduplication still works. */ }
  }
  function panelOpen(open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) { unread = 0; document.getElementById('trade-alert-count').textContent = '0'; document.getElementById('trade-alert-close').focus(); }
    else toggle.focus();
  }
  toggle.addEventListener('click', () => panelOpen(panel.hidden));
  document.getElementById('trade-alert-close').addEventListener('click', () => panelOpen(false));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) panelOpen(false); });
  desktop.addEventListener('click', async () => {
    if (!('Notification' in window) || !window.isSecureContext) {
      desktop.textContent = 'Desktop alerts unavailable here; in-app alerts stay on'; return;
    }
    try {
      const permission = await Notification.requestPermission();
      desktopEnabled = permission === 'granted';
      desktop.textContent = desktopEnabled ? 'Desktop notifications enabled' : 'Desktop permission not granted';
    } catch { desktop.textContent = 'Use in-app alerts on this browser'; }
  });
  function eventText(event, payload) {
    const label = { opened: 'Opened', increased: 'Position increased', closed: 'Closed', partial_close: 'Partial close', reversed: 'Position reversed' }[event.kind] || event.kind;
    const title = `${event.symbol} ${event.side.toUpperCase()} · ${label}${event.outcome ? ` · ${event.outcome.toUpperCase()}` : ''}`;
    const amount = Number(event.pnl);
    const formatted = payload.currency ? amount.toFixed(2) : Number(amount.toPrecision(6)).toString();
    const pnl = event.pnl == null ? (event.kind === 'closed' ? 'Result unavailable' : '') : `${event.kind === 'partial_close' ? 'Exit deal P/L' : 'Net P/L'} ${formatted} ${payload.currency || 'units'}`;
    return { title, body: `${event.volume} lots · ${payload.source.toUpperCase()} ${payload.mode} · ${pnl}` };
  }
  function notify(event, payload) {
    const text = eventText(event, payload);
    const toast = document.createElement('article');
    toast.className = `trade-toast ${event.outcome || ''}`;
    const dismiss = document.createElement('button');
    dismiss.type = 'button'; dismiss.textContent = 'Close'; dismiss.setAttribute('aria-label', `Dismiss ${text.title}`);
    dismiss.addEventListener('click', () => toast.remove());
    const title = document.createElement('strong'); title.textContent = text.title;
    const body = document.createElement('span'); body.textContent = text.body;
    toast.append(dismiss, title, body); toasts.append(toast);
    while (toasts.children.length > 3) toasts.firstElementChild.remove();
    setTimeout(() => toast.remove(), 12000);
    if (panel.hidden) { unread++; document.getElementById('trade-alert-count').textContent = String(unread); }
    try { window.PantherTradeSounds?.play(event); } catch { /* Audio must never interrupt visual alerts or polling. */ }
    if (desktopEnabled && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification(text.title, { body: text.body, tag: `${scope}:${event.id}`, silent: true }); } catch { /* In-app notification remains available. */ }
    }
  }
  function consume(payload) {
    if (!payload.scope || !Array.isArray(payload.events) || !Number.isFinite(payload.asOf)) throw new Error('Invalid event response');
    if (scope !== payload.scope) {
      window.PantherTradeSounds?.silence();
      scope = payload.scope;
      state = load(storageKey(scope));
      if (!state || !Array.isArray(state.seen) || !Array.isArray(state.events) || !Number.isFinite(state.cursor)) state = null;
      unread = 0; document.getElementById('trade-alert-count').textContent = '0'; toasts.replaceChildren();
    }
    const baseline = !state;
    if (!state) state = { seen: [], events: [], cursor: payload.asOf };
    const seen = new Set(state.seen);
    for (const event of payload.events) {
      if (seen.has(event.id)) continue;
      seen.add(event.id);
      state.events.push(event);
      if (!baseline && event.time >= state.cursor - 60) notify(event, payload);
    }
    state.seen = [...seen].slice(-5000);
    state.events = state.events.sort((a, b) => a.time - b.time).slice(-200);
    state.cursor = payload.asOf; cursor = payload.asOf;
    save();
    history.replaceChildren();
    for (const event of [...state.events].reverse()) {
      const text = eventText(event, payload);
      const item = document.createElement('li'); item.className = `trade-event ${event.outcome || ''}`;
      const title = document.createElement('strong'); title.textContent = text.title;
      const details = document.createElement('small'); details.textContent = `${text.body} · ${new Date(event.time * 1000).toLocaleString()}`;
      item.append(title, details); history.append(item);
    }
    status.textContent = `${payload.source.toUpperCase()} ${payload.mode} · Connected · Checks every 5s while this page is open. Recent history retained; older trades do not pop up on first connection.`;
  }
  async function poll() {
    if (busy) return;
    busy = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(`/api/trade-events${cursor == null ? '' : `?since=${cursor}`}`, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('Trade events unavailable');
      consume(await response.json());
    } catch { status.textContent = 'Notifications paused: broker or server unavailable. Retrying automatically.'; }
    finally { clearTimeout(timeout); busy = false; }
  }
  poll();
  setInterval(poll, 5000);
})();
