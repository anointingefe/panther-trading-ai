// Broker-free integration checks for chart updates and notification lifecycle.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const root = path.resolve(__dirname, '../web');
  const server = http.createServer(async (req, res) => {
    const file = path.resolve(root, '.' + (req.url === '/' ? '/index.html' : req.url));
    if (!file.startsWith(root + path.sep)) return res.writeHead(403).end();
    try {
      res.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[path.extname(file)] || 'text/plain');
      res.end(await fs.readFile(file));
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => {
      const NativeAudioContext = window.AudioContext;
      window.soundProbe = { contexts: [], tones: [], attempts: 0 };
      window.AudioContext = class extends NativeAudioContext {
        constructor(...args) { super(...args); window.soundProbe.contexts.push(this); }
        createOscillator() {
          const oscillator = super.createOscillator();
          const start = oscillator.start.bind(oscillator);
          oscillator.start = when => {
            window.soundProbe.tones.push({ frequency: oscillator.frequency.value, when });
            return start(when);
          };
          return oscillator;
        }
      };
    });
    await page.clock.install();
    let payload = { scope: 'account-a', source: 'mt5', mode: 'demo', currency: 'GBP', asOf: 1700000000, events: [] };
    let offline = false;
    await page.route('**/api/**', route => route.fulfill({
      status: !offline && route.request().url().includes('/trade-events') ? 200 : 503,
      contentType: 'application/json', body: JSON.stringify(payload),
    }));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('Connected'));
    await page.evaluate(() => {
      const play = window.PantherTradeSounds.play;
      window.PantherTradeSounds.play = event => { window.soundProbe.attempts++; return play(event); };
    });
    assert.equal(await page.evaluate(() => soundProbe.tones.length), 0, 'First connection must be silent');
    await page.locator('.nav-list a[href="#overview"]').click();
    const candles = Array.from({ length: 120 }, (_, i) => {
      const open = 1.1 + Math.sin(i / 7) * .005;
      const close = open + Math.sin(i) * .001;
      return { time: new Date((1700000000 + i * 900) * 1000).toISOString(), open, close, high: Math.max(open, close) + .0005, low: Math.min(open, close) - .0005, volume: 100 + i };
    });
    const structure = { symbol: 'EURUSD', timeframe: 'M15', source: 'mt5', digits: 5, candles };
    await page.evaluate(s => window.PantherChart.render(s), structure);
    assert.equal(await page.locator('#candle-chart').getAttribute('data-candles'), '120');
    assert.ok(await page.locator('#candle-chart canvas').count() >= 2);
    const old = await page.locator('#candle-readout').textContent();
    candles.at(-1).close += .0001;
    candles.at(-1).high = Math.max(candles.at(-1).high, candles.at(-1).close);
    await page.evaluate(s => window.PantherChart.render(s), structure);
    assert.notEqual(await page.locator('#candle-readout').textContent(), old);
    await page.locator('#structure-chart').scrollIntoViewIfNeeded();
    await page.clock.runFor(100);
    await page.locator('#structure-chart').screenshot({ path: '/tmp/panther-candles-desktop.png' });
    await page.locator('#trade-alert-toggle').click();
    await page.locator('#trade-sound-enabled').check();
    await page.waitForFunction(() => document.getElementById('trade-sound-status').textContent.includes('ready'));
    assert.deepEqual(await page.evaluate(() => soundProbe.tones.map(t => t.frequency)), [660, 880], 'Enable previews the opening sound through real Web Audio');
    await page.locator('#trade-alert-close').click();
    payload.events.push({ id: 'deal:1', kind: 'opened', symbol: 'EURUSD', side: 'buy', volume: .01, time: 1700000001, pnl: null, outcome: null });
    payload.asOf += 5;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelectorAll('.trade-toast').length === 1);
    assert.equal(await page.evaluate(() => soundProbe.attempts), 1);
    assert.equal(await page.evaluate(() => soundProbe.tones.length), 4);
    await page.clock.runFor(5000);
    assert.equal(await page.locator('.trade-toast').count(), 1, 'Duplicate poll must not repeat alert');
    assert.equal(await page.evaluate(() => soundProbe.attempts), 1, 'Duplicate poll must not repeat sound');
    payload.events.push({ ...payload.events[0], id: 'deal:2', kind: 'closed', time: 1700000006, pnl: -1.25, outcome: 'loss' });
    payload.asOf += 5;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelector('.trade-toast.loss'));
    assert.match(await page.locator('.trade-toast.loss').textContent(), /-1.25 GBP/);
    assert.deepEqual(await page.evaluate(() => soundProbe.tones.slice(-2).map(t => t.frequency)), [440, 330]);
    await page.locator('#trade-alert-toggle').click();
    assert.equal(await page.locator('.trade-event').count(), 2);
    assert.equal(await page.locator('.trade-toast:visible').count(), 0, 'Popup stack must not cover notification controls');
    await page.locator('#trade-alert-panel').screenshot({ path: '/tmp/panther-sounds-desktop.png' });
    await page.locator('#trade-sound-volume').focus();
    await page.locator('#trade-sound-volume').press('Home');
    for (let step = 0; step < 5; step++) await page.locator('#trade-sound-volume').press('ArrowRight');
    assert.equal(await page.locator('#trade-sound-level').textContent(), '25%');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: '/tmp/panther-alerts-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    offline = true;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('paused'));
    offline = false;
    payload = { ...payload, scope: 'account-b', events: [], asOf: 1700000030 };
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('Connected'));
    assert.equal(await page.locator('.trade-event').count(), 0, 'Account history must stay separate');
    assert.equal(await page.locator('.trade-toast').count(), 0);
    const tonesBefore = await page.evaluate(() => soundProbe.tones.length);
    payload.events.push({ id: 'deal:3', kind: 'closed', symbol: 'EURUSD', side: 'buy', volume: .01, time: 1700000031, pnl: .00005, outcome: 'win' });
    payload = { ...payload, currency: '', source: 'paper', asOf: 1700000035 };
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelector('.trade-toast.win'));
    assert.match(await page.locator('.trade-toast.win').textContent(), /0\.00005 units/, 'Small paper results must not round to zero');
    assert.equal(await page.evaluate(() => soundProbe.tones.length), tonesBefore + 3);
    assert.deepEqual(await page.evaluate(() => soundProbe.tones.slice(-3).map(t => t.frequency)), [523, 659, 784]);
    await page.locator('#trade-sound-enabled').uncheck();
    payload.events.push({ ...payload.events[0], id: 'deal:4', kind: 'partial_close', outcome: null, time: 1700000036 });
    payload.asOf += 5;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelectorAll('.trade-event').length === 2);
    assert.equal(await page.evaluate(() => soundProbe.tones.length), tonesBefore + 3, 'Muted events still show but never play');
    assert.equal(await page.locator('.trade-toast').count(), 2);
    await page.reload();
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('Connected'));
    await page.locator('#trade-alert-toggle').click();
    assert.equal(await page.locator('#trade-sound-enabled').isChecked(), false, 'Mute survives reload');
    assert.equal(await page.locator('#trade-sound-volume').inputValue(), '25', 'Volume survives reload');
    assert.equal(await page.evaluate(() => soundProbe.tones.length), 0, 'History must not replay audio on reload');
    assert.equal(await page.locator('.trade-toast').count(), 0);
    await page.locator('#trade-sound-enabled').check();
    await page.waitForFunction(() => soundProbe.tones.length === 2);
    await page.reload();
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('Connected'));
    assert.equal(await page.locator('#trade-sound-enabled').isChecked(), true, 'Enabled preference survives reload');
    assert.equal(await page.evaluate(() => soundProbe.contexts.length), 0, 'Saved preference must still wait for user gesture');
    await page.locator('#trade-alert-toggle').click();
    await page.waitForFunction(() => document.getElementById('trade-sound-status').textContent.includes('ready'));
    assert.equal(await page.evaluate(() => soundProbe.tones.length), 0, 'Unlock must not replay missed sounds');
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const panelOverflow = await page.locator('#trade-alert-panel').evaluate(el => el.scrollWidth > el.clientWidth);
      assert.equal(panelOverflow, false, `Notification controls overflow at ${width}px`);
    }
    // Broken chart dependency must degrade to visible candles, not a blank panel.
    await page.route('**/vendor/lightweight-charts-5.0.9.js', route => route.abort());
    await page.reload();
    await page.locator('.nav-list a[href="#overview"]').click();
    await page.evaluate(s => {
      document.getElementById('market-select').innerHTML = '<option value="EURUSD">EURUSD</option>';
      document.getElementById('timeframe-select').value = 'M15';
      renderMarketStructure(s);
    }, structure);
    assert.ok(await page.locator('#candle-layer').isVisible());
    assert.equal(await page.locator('#candle-layer rect').count(), 120);
    assert.equal(await page.locator('#candle-chart').isVisible(), false);
    assert.match(await page.locator('#chart-data-note').textContent(), /basic candles/);
    await page.unroute('**/vendor/lightweight-charts-5.0.9.js');
    await page.route('**/vendor/lightweight-charts-5.0.9.js', route => route.fulfill({
      contentType: 'text/javascript', body: 'window.LightweightCharts = { createChart() { throw new Error("Unavailable canvas"); } };',
    }));
    await page.reload();
    await page.locator('.nav-list a[href="#overview"]').click();
    await page.evaluate(s => {
      document.getElementById('market-select').innerHTML = '<option value="EURUSD">EURUSD</option>';
      document.getElementById('timeframe-select').value = 'M15';
      renderMarketStructure(s);
    }, structure);
    assert.ok(await page.locator('#candle-layer').isVisible(), 'Initialization failure must preserve fallback');
    assert.equal(await page.locator('#candle-layer rect').count(), 120);
    assert.match(await page.locator('#chart-data-note').textContent(), /could not start/);
    assert.deepEqual(errors, []);
    console.log('PASS: candles and fallback, trade sounds, deduplication, net outcomes, mute, volume, persistence, reload, account isolation, responsive controls');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
