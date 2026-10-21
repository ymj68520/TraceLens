// Actual KnowledgeGraph page, HTTP-boundary synthetic data, no live backends.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { peopleRun, peopleRunId, peopleGraphFixture, peopleDetailFixture } from '../web/src/test/fixtures/peopleGraph.js';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const { createServer } = require('vite');
const react = require('@vitejs/plugin-react').default;
const puppeteer = require('puppeteer');
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'tracelens-people-browser-'));
const entry = `
import React from 'react';
import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom';
import {Provider} from 'react-redux';
import {configureStore} from '@reduxjs/toolkit';
import KnowledgeGraph from '/src/pages/KnowledgeGraph.jsx';
import '/src/styles/index.css';
const store=configureStore({reducer:{tasks:()=>({tasks:[{id:'T',status:'completed',image_path:'合成任务T'},{id:'U',status:'completed',image_path:'合成任务U'}]})}});
createRoot(document.getElementById('root')).render(React.createElement(Provider,{store},
React.createElement(MemoryRouter,{initialEntries:['/knowledge-graph?task_id=T']},React.createElement(KnowledgeGraph))));
`;
const server = await createServer({
  root: fileURLToPath(new URL('../web/', import.meta.url)), configFile: false, envFile: false, envDir: false,
  envPrefix: '__PEOPLE_TEST_UNUSED_', logLevel: 'warn',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'import.meta.env.VITE_PYTHON_API_URL': '"/python"', 'import.meta.env.VITE_FIELD_AUTH': '"disabled"' },
  server: { host: '127.0.0.1', port: 0, proxy: {}, hmr: false },
  plugins: [react(), {
    name: 'people-graph-test',
    resolveId(id) { if (id === '/__people-entry.js') return '\0people-entry'; },
    load(id) { if (id === '\0people-entry') return entry; },
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url === '/__people-test.html') {
          res.setHeader('Content-Type', 'text/html');
          res.end(await vite.transformIndexHtml(req.url, '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/__people-entry.js"></script></html>'));
        } else if (/^\/(api|python|tasks|csapi)\b/.test(req.url)) {
          res.statusCode = 503; res.end('Synthetic interception required');
        } else next();
      });
    },
  }],
});
const results = { mode: 'SYNTHETIC_UI_ONLY', output, scenarios: [] };
const hold = () => { let release; const promise = new Promise(done => { release = done; }); return { promise, release }; };
const until = async condition => {
  const end = Date.now() + 10000;
  while (!condition()) {
    if (Date.now() > end) throw new Error('Synthetic condition timed out');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
};
const waitText = (page, text) => page.waitForFunction(text => document.body.innerText.includes(text), {}, text);
const choose = (page, text) => page.click(`button::-p-text(${text})`);
async function fill(page, selector, value) {
  await page.focus(selector);
  await page.keyboard.down('Control'); await page.keyboard.press('KeyA'); await page.keyboard.up('Control');
  await page.keyboard.press('Backspace'); await page.keyboard.sendCharacter(value);
}
async function controls(page) {
  await page.$eval('[aria-label="图谱分析人"]', e => { e.closest('details').open = true; });
  await fill(page, '[aria-label="图谱分析人"]', '合成分析员');
}
let browser, origin;
async function test(name, run) {
  if (process.env.PEOPLE_BROWSER_FILTER && !name.includes(process.env.PEOPLE_BROWSER_FILTER)) return;
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  await page.setViewport({ width: 1440, height: 1080 });
  await page.setBypassServiceWorker(true);
  const state = { errors: [], unexpected: [], requests: [], posts: [], runs: [peopleRun()], holds: [], graphCalls: [] };
  state.hold = () => { const h = hold(); state.holds.push(h); return h; };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      if (request.url().startsWith('data:')) { await request.continue(); return; }
      const url = new URL(request.url());
      if (url.origin !== origin) { state.unexpected.push(request.url()); await request.abort(); return; }
      const pathname = url.pathname.replace(/^\/python(?=\/)/, '');
      if (!pathname.startsWith('/api/')) { await request.continue(); return; }
      const params = Object.fromEntries(url.searchParams);
      const body = request.postData() ? JSON.parse(request.postData()) : null;
      state.requests.push({ path: pathname, method: request.method(), params });
      const reply = (data, status = 200) => request.respond({ status, contentType: 'application/json', body: JSON.stringify(data) });
      if (request.method() === 'POST') {
        if (!pathname.startsWith('/api/graphiti/people-analysis/')) { state.unexpected.push(pathname); await reply({}, 500); return; }
        state.posts.push({ path: pathname, body, params });
        if (state.postGate) await state.postGate.promise;
        const id = 'pg_' + String(state.posts.length + 1).repeat(32);
        const next = peopleRun(id, pathname.includes('/identity/review') ? 'completed' : 'running');
        if (pathname.endsWith('/cancel')) {
          state.runs[0].status = 'cancelled';
          await reply(state.runs[0]); return;
        }
        state.runs.unshift(next);
        await reply(next, 202); return;
      }
      if (pathname === '/api/graphiti/people-analysis/runs') {
        await reply({ runs: params.task_id === 'T' ? state.runs : [] }); return;
      }
      if (/\/people-analysis\/runs\/[^/]+\/graph$/.test(pathname)) {
        const id = pathname.split('/')[5];
        const filters = { ...params, include_context: params.include_context === 'true', max_nodes: Number(params.max_nodes || 200) };
        state.graphCalls.push({ ...filters, run_id: id });
        const data = peopleGraphFixture(filters, id, params.task_id);
        if (state.stale) data.freshness.materials_changed = true;
        if (state.queryGate && params.query === '张') await state.queryGate.promise;
        await reply(data); return;
      }
      if (/\/people-analysis\/runs\/[^/]+\/targets\/[^/]+$/.test(pathname)) {
        const data = peopleDetailFixture(pathname.split('/').pop());
        if (state.detailGate) await state.detailGate.promise;
        await reply(data); return;
      }
      if (/\/people-analysis\/runs\/[^/]+$/.test(pathname)) {
        const id = pathname.split('/').pop();
        const row = state.runs.find(r => r.run_id === id);
        if (state.completeOnPoll && row) { row.status = 'completed'; row.progress = 100; }
        await reply(row || {}); return;
      }
      if (pathname.startsWith('/api/tasks/')) { await reply({ id: pathname.split('/').pop(), case_description: '合成案情：核查付款安排。' }); return; }
      if (pathname === '/api/graphiti/status') { await reply({ task_id: params.task_id, neo4j_connected: false, read_only: true, total_entities: 0, total_relationships: 0 }); return; }
      if (pathname === '/api/graphiti/jobs') { await reply({ jobs: [] }); return; }
      state.unexpected.push(pathname); await reply({}, 500);
    } catch (error) { if (!page.isClosed()) state.errors.push(error.stack); }
  });
  try {
    await page.goto(`${origin}/__people-test.html`, { waitUntil: 'networkidle0' });
    await choose(page, '人员关系图');
    await page.waitForSelector('[data-testid="people-list"]');
    await run(page, state);
    assert.deepEqual(state.errors, []);
    assert.deepEqual(state.unexpected, []);
    results.scenarios.push({ name, status: 'PASS', requests: state.requests.length });
    console.log(`PASS ${name}`);
  } catch (error) {
    const screenshot = path.join(output, `${results.scenarios.length + 1}-failed.png`);
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
    results.scenarios.push({ name, status: 'FAIL', error: error.stack, errors: state.errors, unexpected: state.unexpected, screenshot });
    console.log(`FAIL ${name}: ${error.message}`);
  } finally { state.holds.forEach(h => h.release()); await context.close(); }
}
try {
  await server.listen(); origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || (process.platform === 'win32'
    ? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' : undefined),
    headless: true, args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run'] });
  results.browser = await browser.version();
  await test('stored people render without Neo4j or automatic analysis; isolated candidates retained', async (page, state) => {
    await waitText(page, '王五');
    await waitText(page, '张三（待区分）');
    assert.equal(state.posts.length, 0);
    assert.ok(await page.$('[data-testid="people-graph-canvas"] canvas'));
    await page.screenshot({ path: path.join(output, 'people-desktop.png'), fullPage: true });
  });
  await test('core filter and context toggle preserve the independent priorities', async (page, state) => {
    await page.select('[aria-label="图谱优先级"]', 'core');
    await waitText(page, '筛选命中 1 项');
    assert.equal(await page.$$eval('[data-testid="people-list"] tbody tr', rows => rows.length), 1);
    await page.click('input[type="checkbox"]:not([aria-label])');
    await until(() => state.graphCalls.some(q => q.priority === 'core' && q.include_context));
    await waitText(page, '画布显示 2 个节点');
    assert.equal(state.posts.length, 0);
  });
  await test('typing filters retains focus and rejects a late prior filter result', async (page, state) => {
    state.queryGate = state.hold();
    const selector = '[aria-label="图谱名称搜索"]';
    await page.focus(selector); await page.keyboard.sendCharacter('张');
    await until(() => state.graphCalls.some(q => q.query === '张'));
    assert.equal(await page.$eval(selector, e => e === document.activeElement), true);
    await page.keyboard.sendCharacter('三');
    await until(() => state.graphCalls.some(q => q.query === '张三'));
    await waitText(page, '筛选命中 2 项');
    state.queryGate.release();
    await page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await page.$eval(selector, e => e.value), '张三');
    assert.equal(await page.$$eval('[data-testid="people-list"] tbody tr', rows => rows.length), 2);
  });
  await test('source drawer escapes content and confines keyboard focus', async (page) => {
    await choose(page, '依据与来源');
    await page.waitForSelector('[role="dialog"]');
    await waitText(page, '<img src=x');
    assert.equal(await page.evaluate(() => window.__injected), undefined);
    await page.keyboard.down('Shift'); await page.keyboard.press('Tab'); await page.keyboard.up('Shift');
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('[role="dialog"]')), true);
    await page.keyboard.press('Escape');
    await page.waitForSelector('[role="dialog"]', { hidden: true });
  });
  await test('identity merge creates a new version with exact candidate ids and reason', async (page, state) => {
    await controls(page);
    await page.click('[aria-label="选择人员 张三"]');
    await page.click('[aria-label="选择人员 张三（待区分）"]');
    await page.$eval('[aria-label="身份调整依据"]', e => { e.closest('details').open = true; });
    await fill(page, '[aria-label="身份调整依据"]', '合成身份核查依据');
    await choose(page, '将所选候选归组为一人');
    await until(() => state.posts.length === 1);
    assert.deepEqual(state.posts[0].body.person_ids, ['p1', 'p4']);
    assert.equal(state.posts[0].body.reason, '合成身份核查依据');
    assert.ok(state.posts[0].path.endsWith('/identity/review'));
    await page.waitForFunction(() => document.querySelector('[aria-label="人员图谱版本"]').options.length === 2);
    assert.equal(state.runs[1].run_id, peopleRunId);
  });
  await test('identity split uses selected source mentions and preserves previous version', async (page, state) => {
    await controls(page);
    await choose(page, '依据与来源');
    await page.waitForSelector('[aria-label="拆分提及 m01"]');
    await page.click('[aria-label="拆分提及 m01"]');
    await fill(page, '[aria-label="拆分依据"]', '分别核对两个身份');
    await choose(page, '将所选提及拆为另一人员候选');
    await until(() => state.posts.length === 1);
    assert.deepEqual(state.posts[0].body.mention_ids, ['m01']);
    assert.equal(state.posts[0].body.operation, 'split');
  });
  await test('discovery completes into its exact version and never triggers ingestion or reports', async (page, state) => {
    await controls(page);
    state.completeOnPoll = true;
    await page.click('[data-testid="discover-people"]');
    await until(() => state.posts.length === 1);
    assert.equal(state.posts[0].body.mode, 'discover');
    await page.waitForFunction(() => document.querySelector('[aria-label="人员图谱版本"]').value !== 'pg_' + '1'.repeat(32));
    await page.waitForSelector('[data-testid="people-list"]');
    assert.ok(state.posts.every(r => r.path.startsWith('/api/graphiti/people-analysis/')));
  });
  await test('switching task ignores old graph response and resets old selection', async (page, state) => {
    state.queryGate = state.hold();
    await fill(page, '[aria-label="图谱名称搜索"]', '张');
    await until(() => state.graphCalls.some(q => q.query === '张'));
    await page.select('select:not([aria-label])', 'U');
    state.queryGate.release();
    await page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await page.$('[data-testid="people-list"]'), null);
  });
  await test('relationship priority view shares saved run and only queries edge filters', async (page, state) => {
    const historyId = 'pg_' + '9'.repeat(32);
    state.runs.push(peopleRun(historyId));
    await choose(page, '刷新版本');
    await page.waitForFunction(() => document.querySelector('[aria-label="人员图谱版本"]').options.length === 2);
    await page.select('[aria-label="人员图谱版本"]', historyId);
    await until(() => state.graphCalls.some(q => q.run_id === historyId));
    await choose(page, '优先级关系网');
    await page.waitForSelector('[data-testid="people-list"]');
    assert.equal(await page.$eval('[aria-label="人员图谱版本"]', e => e.value), historyId);
    await page.select('[aria-label="图谱优先级"]', 'P1');
    await until(() => state.graphCalls.some(q => q.view === 'relations' && q.priority === 'P1'));
    await waitText(page, '张三 — 安排付款 → 李四');
    assert.equal(state.posts.length, 0);
  });
  await test('stale materials show historic result and prevent identity edits', async (page, state) => {
    state.stale = true;
    await choose(page, '刷新版本');
    await waitText(page, '当前显示历史冻结结果');
    await controls(page);
    await page.click('[aria-label="选择人员 张三"]');
    await page.click('[aria-label="选择人员 张三（待区分）"]');
    await page.$eval('[aria-label="身份调整依据"]', e => { e.closest('details').open = true; });
    await fill(page, '[aria-label="身份调整依据"]', '核查');
    assert.equal(await page.$eval('button::-p-text(将所选候选归组为一人)', e => e.disabled), true);
  });
  await test('people panel remains usable at 390px and 320px in dark mode', async (page) => {
    for (const width of [390, 320]) {
      await page.setViewport({ width, height: 1000 });
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `overflow at ${width}`);
      await page.screenshot({ path: path.join(output, `people-mobile-${width}.png`), fullPage: true });
      await choose(page, '依据与来源');
      await page.waitForSelector('[role="dialog"]');
      await waitText(page, '<img src=x');
      assert.equal(await page.$eval('[data-testid="people-source-overlay"]', e => {
        const r = e.getBoundingClientRect();
        return r.top === 0 && r.left === 0 && r.right === innerWidth && r.bottom === innerHeight;
      }), true, 'source overlay must cover the viewport, not the glass card');
      assert.ok(await page.$eval('[role="dialog"] header', e => {
        const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight;
      }), 'source header must be visible after opening from a scrolled page');
      assert.ok(await page.$eval('[role="dialog"]', e => e.scrollWidth <= e.clientWidth + 1));
      await page.screenshot({ path: path.join(output, `people-source-${width}.png`) });
      await page.keyboard.press('Escape');
      await page.waitForSelector('[role="dialog"]', { hidden: true });
    }
  });
} finally {
  await browser?.close(); await server.close();
  results.passed = results.scenarios.filter(r => r.status === 'PASS').length;
  results.failed = results.scenarios.filter(r => r.status === 'FAIL').length;
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(`Results: ${results.passed} passed, ${results.failed} failed. ${path.join(output, 'results.json')}`);
}
if (results.failed) process.exitCode = 1;
