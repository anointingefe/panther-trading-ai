// Run with Node and Playwright installed. All API traffic is mocked: no broker calls.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

async function main() {
  const root = path.resolve(__dirname, '../web');
  const server = http.createServer(async (req, res) => {
    const file = path.resolve(root, '.' + (req.url === '/' ? '/index.html' : req.url));
    if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    try {
      const body = await fs.readFile(file);
      res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[path.extname(file)] || 'text/plain');
      res.end(body);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const errors = [];
    const requests = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => {
      requests.push({ url: route.request().url(), method: route.request().method(), body: route.request().postDataJSON() });
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Offline test fixture' }) });
    });
    const url = `http://127.0.0.1:${server.address().port}`;
    await page.goto(url);
    await page.waitForFunction(() => document.querySelectorAll('.workspace-view').length === 6);
    const original = await fs.readFile(path.join(root, 'index.html'), 'utf8');
    const missing = await page.evaluate(html => {
      const old = new DOMParser().parseFromString(html, 'text/html');
      return [...old.querySelectorAll('[id]')].map(el => el.id).filter(id => !document.getElementById(id));
    }, original);
    assert.deepEqual(missing, [], 'All original element IDs must be retained');
    assert.equal(await page.locator('.lower-grid').count(), 0, 'All original panels must be assigned a workspace');
    const ids = await page.locator('[id]').evaluateAll(nodes => nodes.map(n => n.id));
    assert.equal(ids.length, new Set(ids).size, 'IDs must remain unique');

    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 960 });
      for (const view of ['overview', 'markets', 'execution', 'research', 'performance', 'settings']) {
        await page.locator(`.nav-list a[href="#${view}"]`).click();
        assert.equal(await page.locator('.workspace-view:visible').count(), 1);
        assert.equal(await page.locator('.nav-list [aria-current="page"]').getAttribute('href'), `#${view}`);
        assert.equal(await page.evaluate(() => document.activeElement.id), 'workspace-title');
        const overflowing = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => {
          const box = el.getBoundingClientRect();
          return box.width && box.right > innerWidth + 1 && !el.closest('.nav-list');
        }).map(el => `${el.tagName}.${el.className}#${el.id}`));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${view} overflows at ${width}px: ${overflowing.join(', ')}`);
        assert.ok(await page.locator('#emergency-stop').isVisible());
        const clipped = await page.locator('.workspace-view:visible button, .workspace-view:visible input, .workspace-view:visible select').evaluateAll(nodes => nodes.filter(n => {
          const rect = n.getBoundingClientRect();
          return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1);
        }).map(n => n.id || n.textContent));
        assert.deepEqual(clipped, [], `${view} controls clip at ${width}px`);
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('a[href="#overview"]').click();
    await page.locator('a[href="#execution"]').click();
    await page.goBack();
    assert.ok(await page.locator('#overview').isVisible());
    await page.goForward();
    assert.ok(await page.locator('#execution').isVisible());
    for (const [control, endpoint] of [
      ['demo-auto-cycle', '/api/demo-auto/cycle'], ['demo-auto-start', '/api/demo-auto/start'],
      ['demo-auto-stop', '/api/demo-auto/stop'], ['live-auto-cycle', '/api/live-auto/cycle'],
      ['live-auto-start', '/api/live-auto/start'], ['live-auto-stop', '/api/live-auto/stop'],
    ]) {
      await page.locator(`#${control}`).click();
      await page.waitForFunction(() => !document.getElementById('live-auto-message').textContent.includes('Updating live loop'));
      assert.ok(requests.some(r => r.method === 'POST' && r.url.endsWith(endpoint)), `${control} retains its endpoint`);
    }
    await page.locator('a[href="#performance"]').click();
    await page.locator('#goal-daily').fill('25');
    await page.locator('#goals-form button').click();
    assert.ok(requests.some(r => r.url.endsWith('/api/goals') && r.method === 'POST' && r.body.dailyTarget === '25'));
    await page.locator('a[href="#overview"]').click();
    await page.locator('#run-scan').click();
    await page.waitForFunction(() => !document.getElementById('run-scan').disabled);
    assert.ok(requests.some(r => r.url.includes('/api/snapshot?') && r.url.includes('record=true')));
    await page.evaluate(() => renderApproval({ id: 'test-only', approval_status: 'pending_approval', symbol: 'EURUSD', side: 'buy', entry: 1.1, confidence: 0.7 }));
    for (const [button, decision] of [['approve-signal', 'approved'], ['reject-signal', 'rejected']]) {
      await page.locator(`#${button}`).click();
      assert.ok(requests.some(r => r.url.endsWith('/api/journal/decision') && r.body?.decision === decision));
    }
    await page.locator('#emergency-stop').click();
    assert.ok(requests.some(r => r.url.endsWith('/api/positions/close-all') && r.method === 'POST'));
    await page.goto(url + '/#backtests-section');
    assert.ok(await page.locator('#research').isVisible(), 'Legacy bookmarks resolve');
    await page.locator('a[href="#overview"]').click();
    await page.evaluate(() => renderDashboard(fallbackSnapshot));
    await page.screenshot({ path: path.join(os.tmpdir(), 'panther-overview-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(os.tmpdir(), 'panther-overview-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('PASS: six workspaces, five viewport sizes, preserved IDs, history, legacy links, mocked control endpoints, no JavaScript errors.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
