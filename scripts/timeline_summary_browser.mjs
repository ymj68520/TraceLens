// Headless actual Timeline/IM pages, HTTP-boundary synthetic fixtures only.
// No project .env, backend proxy, real evidence, model calls, or live dist.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { timelineSummaryFixture, timelineRecordsFixture } from '../web/src/test/fixtures/timelineSummary.js';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const { createServer } = require('vite');
const react = require('@vitejs/plugin-react').default;
const puppeteer = require('puppeteer');
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'tracelens-timeline-browser-'));
const entry = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { ToastContext } from '/src/components/common/toastContext.js';
import Timeline from '/src/pages/Timeline.jsx';
import IMForensics from '/src/pages/IMForensics/IMForensics.jsx';
import '/src/styles/index.css';
const initial = new URLSearchParams(location.search).get('route') || '/timeline?task_id=synthetic-T&view=summary';
const store = configureStore({ reducer: {
  tasks: () => ({tasks:[{id:'synthetic-T',image_path:'synthetic-image'}]}),
  settings: () => ({language:'zh',itemsPerPage:50}), intelligence: (s={}) => s,
} });
createRoot(document.getElementById('root')).render(
  React.createElement(Provider, {store},
    React.createElement(ToastContext.Provider, {value:{show:()=>{}}},
      React.createElement(MemoryRouter, {initialEntries:[initial]},
        React.createElement('div', {style:{maxWidth:1280,margin:'auto',padding:12}},
          React.createElement(Routes, null,
            React.createElement(Route, {path:'/timeline',element:React.createElement(Timeline)}),
            React.createElement(Route, {path:'/im-forensics',element:React.createElement(IMForensics)})))))));
`;
const server = await createServer({
  root: fileURLToPath(new URL('../web/', import.meta.url)), configFile: false, envFile: false, envDir: false,
  envPrefix: '__TIMELINE_TEST_UNUSED_', logLevel: 'warn',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'import.meta.env.VITE_PYTHON_API_URL': '"/python"',
    'import.meta.env.VITE_FIELD_AUTH': '"disabled"' },
  server: { host: '127.0.0.1', port: 0, hmr: false, proxy: {} },
  plugins: [react(), {
    name: 'synthetic-timeline-test',
    resolveId(id) { if (id === '/__timeline-entry.js') return '\0timeline-test-entry'; },
    load(id) { if (id === '\0timeline-test-entry') return entry; },
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url.split('?')[0] === '/__timeline-test.html') {
          res.setHeader('Content-Type', 'text/html');
          res.end(await vite.transformIndexHtml(req.url, '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/__timeline-entry.js"></script></html>'));
        } else if (/^\/(api|python|tasks|csapi)\b/.test(req.url)) {
          res.statusCode = 503; res.end('Synthetic interception required');
        } else next();
      });
    },
  }],
});
const results = { mode: 'SYNTHETIC_UI_ONLY', output, scenarios: [] };
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const gate = () => {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release };
};
const until = async condition => {
  const deadline = Date.now() + 8000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error('Synthetic request did not arrive');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
};
const imRoute = '/im-forensics?platform=wechat&import_id=abcdef123456&tab=timeline';
const generate = async page => {
  await page.click('[data-testid="timeline-summary-generate"]');
  await page.waitForSelector('[data-testid="timeline-summary-result"]');
};
const waitText = (page, text) => page.waitForFunction(text => document.body.innerText.includes(text), {}, text);
const setDate = (page, label, value) => page.$eval(`[aria-label="${label}"]`, (element, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
}, value);
let browser, origin;
async function test(name, route, run) {
  if (process.env.TIMELINE_BROWSER_FILTER && !name.includes(process.env.TIMELINE_BROWSER_FILTER)) return;
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  await page.setViewport({ width: 1440, height: 1100 });
  await page.setBypassServiceWorker(true);
  const state = { errors: [], unexpected: [], requests: [], summaries: [], details: [], truncated: false, stale: false, holds: [] };
  state.hold = () => { const hold = gate(); state.holds.push(hold); return hold; };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      if (request.url().startsWith('data:')) { await request.continue(); return; }
      const url = new URL(request.url());
      if (url.origin !== origin) { state.unexpected.push(request.url()); await request.abort(); return; }
      const pathname = url.pathname.replace(/^\/python(?=\/)/, '');
      if (!pathname.startsWith('/api/')) { await request.continue(); return; }
      state.requests.push({ path: pathname, method: request.method(), params: Object.fromEntries(url.searchParams) });
      const reply = (value, status = 200) => request.respond({ status, contentType: 'application/json', body: JSON.stringify(value) });
      if (request.method() !== 'GET') { state.unexpected.push(pathname); await reply({}, 500); return; }
      if (pathname.endsWith('/timeline-summary')) {
        const params = Object.fromEntries(url.searchParams);
        state.summaries.push({ path: pathname, params });
        const value = timelineSummaryFixture({ truncated: state.truncated, communication: !pathname.startsWith('/api/associations') });
        Object.assign(value.context.filters, params);
        value.context.source_version = hash(pathname);
        value.context.context_id = hash([pathname, params]);
        value.context.scope.scope_id = params.task_id || pathname.split('/')[5];
        if (state.summaryGate) await state.summaryGate.promise;
        state.last = value;
        await reply(value); return;
      }
      if (pathname.endsWith('/timeline-summary/records')) {
        const params = Object.fromEntries(url.searchParams);
        state.details.push({ path: pathname, params });
        if (state.detailGate) await state.detailGate.promise;
        if (state.stale) { await reply({ detail: '来源已更新，请重新生成统计后回查' }, 409); return; }
        assert.equal(params.source_version, state.last.context.source_version);
        assert.equal(params.summary_id, state.last.context.context_id);
        const value = timelineRecordsFixture(state.last.context, { offset: Number(params.offset), limit: 50 });
        if (state.paginated && Number(params.offset) === 0) { value.total = 51; value.page_truncated = true; }
        await reply(value); return;
      }
      if (pathname === '/api/system/features') { await reply({ event_llm_analysis_enabled: false }); return; }
      if (pathname === '/api/forensics/timeline/comprehensive') {
        await reply({ timeline: [{ timestamp: 1767276000, event_type: 'MODIFIED', cluster_count: 1, file_path: '/synthetic/a.txt' }],
          metadata: { total_events: 1 } }); return;
      }
      if (pathname === '/api/forensics/timeline/distribution') {
        await reply({ distribution: [{ event_date: '2026-01-01', event_type: 'MODIFIED', count: 1 }] }); return;
      }
      if (/\/api\/(wechat|qq)\/forensics\/imports$/.test(pathname)) {
        await reply({ imports: pathname.includes('/qq/') ? [{ import_id: '123456abcdef', status: 'ready', name: '合成QQ' }] :
          [{ import_id: 'abcdef123456', status: 'ready', name: '合成微信A' }, { import_id: 'abcdef654321', status: 'ready', name: '合成微信B' }] }); return;
      }
      if (/\/forensics\/imports\/[a-f0-9]+\/overview$/.test(pathname)) { await reply({ stats: {} }); return; }
      state.unexpected.push(pathname); await reply({ detail: 'Unexpected test request' }, 500);
    } catch (error) { if (!page.isClosed()) state.errors.push(error.stack); }
  });
  try {
    await page.goto(`${origin}/__timeline-test.html?route=${encodeURIComponent(route)}`, { waitUntil: 'networkidle0' });
    await page.waitForSelector('[data-testid="timeline-summary"]');
    await run(page, state);
    assert.deepEqual(state.errors, [], 'page/runtime errors');
    assert.deepEqual(state.unexpected, [], 'unexpected API/external requests');
    results.scenarios.push({ name, status: 'PASS', requests: state.requests.length });
    console.log(`PASS ${name}`);
  } catch (error) {
    const screenshot = path.join(output, `${results.scenarios.length + 1}-failed.png`);
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
    results.scenarios.push({ name, status: 'FAIL', error: error.stack, screenshot, errors: state.errors, unexpected: state.unexpected });
    console.log(`FAIL ${name}: ${error.message}`);
  } finally {
    state.holds.forEach(h => h.release());
    await context.close();
  }
}
try {
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || (process.platform === 'win32' ?
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' : undefined), headless: true,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run'] });
  results.browser = await browser.version();
  await test('actual timeline preserves parent filters and does not call a model', '/timeline?task_id=synthetic-T&view=summary&type=MODIFIED&start=1767200000&end=1767500000', async (page, state) => {
    assert.equal(state.summaries.length, 0);
    await generate(page);
    assert.deepEqual(state.summaries[0].params, { task_id: 'synthetic-T', source: 'events', event_type: 'MODIFIED',
      start_time: '1767200000', end_time: '1767500000', timezone: 'Asia/Shanghai' });
    await waitText(page, '前一日未见记录，覆盖未知');
    assert.equal(state.requests.some(r => r.path.includes('/llm/')), false);
  });
  await test('task timeline summary stays usable on a narrow screen', '/timeline?task_id=synthetic-T&view=summary', async (page) => {
    await page.setViewport({ width: 320, height: 1000 });
    await generate(page);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'task page overflow');
    assert.equal(await page.$('main footer'), null);
    await page.click('[aria-label="22时：6条，3个日期"]');
    await page.waitForSelector('[role="dialog"]');
    await waitText(page, '来源表记录标识 12345');
    await page.keyboard.press('Escape');
    await page.screenshot({ path: path.join(output, 'task-summary-320.png'), fullPage: true });
  });
  await test('local dates and timezone are sent explicitly, invalid range blocked', imRoute, async (page, state) => {
    await page.select('[aria-label="分析时区"]', 'America/New_York');
    await setDate(page, '总结开始日期', '2026-11-02');
    await setDate(page, '总结结束日期', '2026-11-01');
    assert.equal(await page.$eval('[data-testid="timeline-summary-generate"]', e => e.disabled), true);
    assert.equal(state.summaries.length, 0);
    await setDate(page, '总结开始日期', '2026-11-01');
    await generate(page);
    assert.equal(state.summaries[0].params.timezone, 'America/New_York');
    assert.equal(state.summaries[0].params.start_date, '2026-11-01');
    assert.equal(state.summaries[0].params.end_date, '2026-11-01');
    await page.select('[aria-label="分析时区"]', 'UTC');
    await page.waitForSelector('[data-testid="timeline-summary-result"]', { hidden: true });
    assert.equal(state.summaries.length, 1);
  });
  await test('communication directions and version-bound escaped source record', imRoute, async (page, state) => {
    await page.select('[aria-label="收发方向"]', 'sent');
    await generate(page);
    await page.click('button::-p-text(发出 3 条)');
    await page.waitForSelector('[role="dialog"]');
    await waitText(page, '来源表记录标识 12345');
    assert.equal(state.details[0].params.direction, 'sent');
    assert.equal(state.details[0].params.record_direction, 'sent');
    assert.equal(await page.evaluate(() => window.__injected), undefined);
    assert.equal(await page.$eval('[role="dialog"]', e => !!e.querySelector('img')), false);
    await page.keyboard.press('Escape');
    await page.waitForSelector('[role="dialog"]', { hidden: true });
  });
  await test('stale source blocks old drilldown and allows regeneration', imRoute, async (page, state) => {
    await generate(page);
    state.stale = true;
    await page.click('button::-p-text(有效 6)');
    await waitText(page, '来源已更新，请重新生成统计后回查');
    await page.click('[aria-label="关闭回查"]');
    assert.equal(await page.$eval('button::-p-text(有效 6)', e => e.disabled), true);
    state.stale = false;
    await generate(page);
    assert.equal(await page.$eval('button::-p-text(有效 6)', e => e.disabled), false);
  });
  await test('switching imports discards a delayed old summary', imRoute, async (page, state) => {
    state.summaryGate = state.hold();
    await page.click('[data-testid="timeline-summary-generate"]');
    await until(() => state.summaries.length === 1);
    await page.select('select:not([aria-label])', 'abcdef654321');
    state.summaryGate.release();
    await page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await page.$('[data-testid="timeline-summary-result"]'), null);
    await generate(page);
    assert.ok(state.summaries[1].path.includes('abcdef654321'));
  });
  await test('switching WeChat to QQ keeps source scopes separate', imRoute, async (page, state) => {
    await generate(page);
    await page.click('button::-p-text(QQ)');
    await page.waitForFunction(() => [...document.querySelectorAll('option')].some(e => e.value === '123456abcdef'));
    assert.equal(await page.$('[data-testid="timeline-summary-result"]'), null);
    await generate(page);
    assert.equal(state.summaries[1].path, '/api/qq/forensics/imports/123456abcdef/timeline-summary');
  });
  await test('late source detail does not reopen a closed drawer', imRoute, async (page, state) => {
    await generate(page);
    state.detailGate = state.hold();
    await page.click('button::-p-text(有效 6)');
    await until(() => state.details.length === 1);
    await page.click('[aria-label="关闭回查"]');
    state.detailGate.release();
    await page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await page.$('[role="dialog"]'), null);
  });
  await test('record pagination retains source version and exact selector', imRoute, async (page, state) => {
    state.paginated = true;
    await generate(page);
    await page.click('[aria-label="22时：6条，3个日期"]');
    await waitText(page, '符合条件 51 条');
    await page.click('button::-p-text(下一页记录)');
    await until(() => state.details.length === 2);
    assert.equal(state.details[1].params.offset, '50');
    assert.equal(state.details[1].params.hour, '22');
    assert.equal(state.details[1].params.source_version, state.details[0].params.source_version);
  });
  await test('truncation and audit metadata remain visible', imRoute, async (page, state) => {
    state.truncated = true;
    await generate(page);
    await waitText(page, '未扫描 100 条');
    await page.click('summary::-p-text(统计口径、来源版本与筛选条件)');
    await waitText(page, 'timeline-summary:v1');
    assert.ok(await page.evaluate(() => document.body.innerText.includes('非原始证据内容哈希')));
  });
  await test('desktop and narrow dark mobile layouts; modal keyboard confinement', imRoute, async (page) => {
    await generate(page);
    for (const [width, dark] of [[1440, false], [390, false], [320, true]]) {
      await page.setViewport({ width, height: 1000 });
      await page.evaluate(dark => document.documentElement.classList.toggle('dark', dark), dark);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `page overflow at ${width}`);
      await page.screenshot({ path: path.join(output, `summary-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true });
      await page.focus('[aria-label="22时：6条，3个日期"]');
      await page.keyboard.press('Enter');
      await page.waitForSelector('[role="dialog"]');
      await waitText(page, '来源表记录标识 12345');
      await page.keyboard.down('Shift'); await page.keyboard.press('Tab'); await page.keyboard.up('Shift');
      assert.equal(await page.evaluate(() => !!document.activeElement.closest('[role="dialog"]')), true);
      assert.equal(await page.$eval('[data-testid="timeline-source-overlay"]', e => e.getBoundingClientRect().top), 0);
      assert.ok(await page.$eval('[role="dialog"]', e => e.scrollWidth <= e.clientWidth + 1));
      await page.screenshot({ path: path.join(output, `source-${width}-${dark ? 'dark' : 'light'}.png`) });
      await page.keyboard.press('Escape');
      await page.waitForSelector('[role="dialog"]', { hidden: true });
      assert.equal(await page.$eval('[aria-label="22时：6条，3个日期"]', e => e === document.activeElement), true);
    }
  });
} finally {
  await browser?.close();
  await server.close();
  results.passed = results.scenarios.filter(s => s.status === 'PASS').length;
  results.failed = results.scenarios.filter(s => s.status === 'FAIL').length;
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(`Results: ${results.passed} passed, ${results.failed} failed. ${path.join(output, 'results.json')}`);
}
if (results.failed) process.exitCode = 1;
