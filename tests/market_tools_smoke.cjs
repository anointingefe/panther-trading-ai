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
    await page.clock.install();
    let payload = { scope: 'account-a', source: 'mt5', mode: 'demo', currency: 'GBP', asOf: 1700000000, events: [] };
    let offline = false;
    await page.route('**/api/**', route => route.fulfill({
      status: !offline && route.request().url().includes('/trade-events') ? 200 : 503,
      contentType: 'application/json', body: JSON.stringify(payload),
    }));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.getElementById('trade-alert-status').textContent.includes('Connected'));
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
    payload.events.push({ id: 'deal:1', kind: 'opened', symbol: 'EURUSD', side: 'buy', volume: .01, time: 1700000001, pnl: null, outcome: null });
    payload.asOf += 5;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelectorAll('.trade-toast').length === 1);
    await page.clock.runFor(5000);
    assert.equal(await page.locator('.trade-toast').count(), 1, 'Duplicate poll must not repeat alert');
    payload.events.push({ ...payload.events[0], id: 'deal:2', kind: 'closed', time: 1700000006, pnl: -1.25, outcome: 'loss' });
    payload.asOf += 5;
    await page.clock.runFor(5000);
    await page.waitForFunction(() => document.querySelector('.trade-toast.loss'));
    assert.match(await page.locator('.trade-toast.loss').textContent(), /-1.25 GBP/);
    await page.locator('#trade-alert-toggle').click();
    assert.equal(await page.locator('.trade-event').count(), 2);
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
    assert.deepEqual(errors, []);
    console.log('PASS: OHLC update, canvas render, alerts, deduplication, net loss, disconnect, account isolation, mobile layout');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
