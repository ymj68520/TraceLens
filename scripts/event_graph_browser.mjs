// Actual graph page/canvas; synthetic HTTP sources, no real model or case access.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { eventGraphFixture, eventDetailFixture, eventRun, eventRunId, eventPeopleId } from '../web/src/test/fixtures/eventGraph.js';

const require = createRequire(new URL('../web/package.json', import.meta.url));
const { createServer } = require('vite');
const react = require('@vitejs/plugin-react').default;
const puppeteer = require('puppeteer');
// Tailwind resolves its project config from cwd even with Vite's root set.
process.chdir(fileURLToPath(new URL('../web/', import.meta.url)));
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'tracelens-event-browser-'));
const entry = `
import React from 'react'; import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom'; import {Provider} from 'react-redux';
import {configureStore} from '@reduxjs/toolkit'; import KnowledgeGraph from '/src/pages/KnowledgeGraph.jsx';
import '/src/styles/index.css';
const store=configureStore({reducer:{tasks:()=>({tasks:[{id:'T',image_path:'合成测试任务',status:'completed'}]})}});
createRoot(document.getElementById('root')).render(React.createElement(Provider,{store},React.createElement(MemoryRouter,
{initialEntries:['/knowledge-graph?task_id=T']},React.createElement(KnowledgeGraph))));`;
const server = await createServer({
  root: fileURLToPath(new URL('../web/', import.meta.url)), configFile: false, envFile: false, envDir: false,
  envPrefix: '__EVENT_TEST_UNUSED_', logLevel: 'warn',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'import.meta.env.VITE_PYTHON_API_URL': '"/python"', 'import.meta.env.VITE_FIELD_AUTH': '"disabled"' },
  server: { host: '127.0.0.1', port: 0, proxy: {}, hmr: false },
  plugins: [react(), {
    name: 'event-graph-test',
    resolveId(id) { if (id === '/__event-entry.js') return '\0event-entry'; },
    load(id) { if (id === '\0event-entry') return entry; },
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url === '/__event-test.html') {
          res.setHeader('Content-Type', 'text/html');
          res.end(await vite.transformIndexHtml(req.url, '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/__event-entry.js"></script></html>'));
        } else if (/^\/(api|python|tasks)\b/.test(req.url)) { res.statusCode = 503; res.end('Synthetic interception required'); }
        else next();
      });
    },
  }],
});
const results = { mode: 'SYNTHETIC_UI_ONLY', output, scenarios: [] };
let browser, origin;
const text = (page, value) => page.waitForFunction(s => document.body.innerText.includes(s), {}, value);
const click = (page, value) => page.click(`button::-p-text(${value})`);
async function test(name, body) {
  const context = await browser.createBrowserContext(), page = await context.newPage();
  const state = { posts: [], unexpected: [], errors: [], queries: [], runs: [eventRun()], unavailable: false };
  page.setDefaultTimeout(15000);
  await page.setViewport({ width: 1440, height: 1080 });
  await page.setBypassServiceWorker(true);
  page.on('pageerror', e => state.errors.push(e.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      if (request.url().startsWith('data:')) { await request.continue(); return; }
      const url = new URL(request.url());
      if (url.origin !== origin) { state.unexpected.push(request.url()); await request.abort(); return; }
      const route = url.pathname.replace(/^\/python(?=\/)/, ''), params = Object.fromEntries(url.searchParams);
      if (!route.startsWith('/api/')) { await request.continue(); return; }
      const reply = (payload, status = 200) => request.respond({ status, contentType: 'application/json', body: JSON.stringify(payload) });
      if (request.method() === 'POST') {
        if (route !== '/api/graphiti/event-analysis/runs') { state.unexpected.push(route); await reply({}, 500); return; }
        state.posts.push(JSON.parse(request.postData()));
        const row = eventRun('pg_' + 'b'.repeat(32), 'running'); state.runs.unshift(row);
        await reply(row, 202); return;
      }
      if (route === '/api/graphiti/event-views') {
        state.queries.push(params);
        await reply(state.unavailable ? { detail: '事件图谱暂不可读' } : eventGraphFixture(params), state.unavailable ? 503 : 200); return;
      }
      if (route === '/api/graphiti/event-views/detail') {
        assert.equal(params.source_version, 'f'.repeat(64)); await reply(eventDetailFixture(params.target_id)); return;
      }
      if (route === '/api/graphiti/event-analysis/runs') { await reply({ runs: state.runs }); return; }
      if (/\/event-analysis\/runs\/[^/]+\/graph$/.test(route)) { await reply(eventGraphFixture(params, route.split('/')[5])); return; }
      if (/\/event-analysis\/runs\/[^/]+\/detail$/.test(route)) { await reply(eventDetailFixture(params.target_id, route.split('/')[5])); return; }
      if (/\/event-analysis\/runs\/[^/]+$/.test(route)) {
        const row = state.runs.find(r => r.run_id === route.split('/').pop()); row.status = 'completed'; await reply(row); return;
      }
      if (route === '/api/graphiti/people-analysis/runs') { await reply({ runs: [eventRun(eventPeopleId)] }); return; }
      if (route === '/api/graphiti/status') { await reply({ task_id: 'T', neo4j_connected: false, read_only: true }); return; }
      if (route === '/api/graphiti/tasks') { await reply({ tasks: [] }); return; }
      if (route === '/api/graphiti/jobs') { await reply({ jobs: [] }); return; }
      state.unexpected.push(route); await reply({}, 500);
    } catch (e) { state.errors.push(e.stack); await request.abort().catch(() => {}); }
  });
  try {
    await page.goto(`${origin}/__event-test.html`, { waitUntil: 'networkidle0' });
    await click(page, '事件—证据图');
    await page.waitForSelector('[data-testid="event-graph-canvas"] canvas');
    await body(page, state);
    assert.deepEqual(state.errors, []); assert.deepEqual(state.unexpected, []);
    results.scenarios.push({ name, status: 'PASS' }); console.log(`PASS ${name}`);
  } catch (e) {
    const screenshot = path.join(output, `failure-${results.scenarios.length}.png`);
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
    results.scenarios.push({ name, status: 'FAIL', error: e.stack, errors: state.errors, unexpected: state.unexpected, screenshot });
    console.log(`FAIL ${name}: ${e.message}`);
  } finally { await context.close(); }
}
try {
  await server.listen(); origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || (process.platform === 'win32' ? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' : undefined), headless: true,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run'] });
  await test('existing event canvas, isolated event and exact shared source without model calls', async (page, state) => {
    await text(page, '孤立事件'); assert.equal(state.posts.length, 0);
    await page.screenshot({ path: path.join(output, 'events-desktop.png'), fullPage: true });
    await click(page, '付款安排 → 共同关联材料'); await text(page, '初次分析摘要；尚未核对原文');
    assert.ok(await page.$('[data-testid="event-source-detail"]'));
  });
  await test('evidence view and association history share a chosen version', async (page, state) => {
    await page.select('[aria-label="事件图谱版本"]', eventRunId);
    await click(page, '智能事件关联'); await text(page, '机器建议 · 待核查');
    await click(page, '张三 → 参与线索'); await text(page, '尚未改变调查事件');
    await click(page, '证据关联图');
    assert.equal(await page.$eval('[aria-label="事件图谱版本"]', e => e.value), eventRunId);
    assert.equal(state.posts.length, 0);
  });
  await test('explicit submit uses exact selected people version and enters completed history', async (page, state) => {
    await page.$eval('[aria-label="事件分析人"]', e => { e.closest('details').open = true; });
    await page.type('[aria-label="事件分析人"]', '合成分析员');
    await page.select('[aria-label="关联人员版本"]', eventPeopleId);
    await click(page, '生成智能关联新版本');
    await page.waitForFunction(() => document.querySelector('[aria-label="事件图谱版本"]').value === 'pg_' + 'b'.repeat(32));
    await text(page, '候选目标对 5');
    assert.equal(state.posts.length, 1); assert.equal(state.posts[0].people_run_id, eventPeopleId);
    await click(page, '智能事件关联'); await text(page, '机器建议 · 待核查');
  });
  await test('communication entry keeps task and import sources distinct', async page => {
    await click(page, '通讯关系图');
    assert.equal(await page.$eval('a[href*="tab=graph&task_id="]', e => e.getAttribute('href')), '/im-forensics?tab=graph&task_id=T');
    assert.ok(await page.$('a[href="/im-forensics?platform=qq&tab=graph"]'));
  });
  await test('unavailable data is a visible error and never triggers analysis', async (page, state) => {
    state.unavailable = true;
    await click(page, '刷新图谱数据'); await text(page, '事件图谱暂不可读');
    assert.equal(state.posts.length, 0);
  });
  for (const width of [390, 320]) await test(`mobile ${width}: canvas and source text stay within viewport`, async page => {
    await page.setViewport({ width, height: 900 });
    await click(page, '付款安排 → 共同关联材料'); await text(page, '图谱来源回查');
    assert.ok(await page.$eval('[data-testid="event-graph-panel"]', e => e.scrollWidth <= e.clientWidth + 1));
    assert.ok(await page.$eval('[data-testid="event-source-detail"]', e => e.scrollWidth <= e.clientWidth + 1));
    await page.screenshot({ path: path.join(output, `events-mobile-${width}.png`), fullPage: true });
  });
} finally {
  await browser?.close(); await server.close();
  results.passed = results.scenarios.filter(r => r.status === 'PASS').length;
  results.failed = results.scenarios.filter(r => r.status === 'FAIL').length;
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(`Results: ${results.passed} passed, ${results.failed} failed. ${path.join(output, 'results.json')}`);
}
if (results.failed) process.exitCode = 1;
