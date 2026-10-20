// Real report page + real HTTP clients, synthetic responses only.
// No backend, provider, existing service, .env, or live web/dist is used.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const { createServer } = require('vite');
const react = require('@vitejs/plugin-react').default;
const puppeteer = require('puppeteer');
const webRoot = fileURLToPath(new URL('../web/', import.meta.url));
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'tracelens-report-browser-'));
const browserPath = process.env.CHROME_BIN || (process.platform === 'win32'
  ? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' : undefined);
const entry = `
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import ForensicReportPage from '/src/pages/ForensicReportPage.jsx';
import '/src/styles/index.css';
function Harness() {
  const [task, setTask] = useState('synthetic-T');
  const [query, setQuery] = useSearchParams();
  return React.createElement('main', { style: { maxWidth: 1152, margin: 'auto', padding: 16 } },
      React.createElement('output', { 'data-testid': 'test-route', hidden: true }, query.toString()),
      React.createElement('label', null, '合成测试任务 ',
        React.createElement('select', { 'aria-label': '合成测试任务', value: task, onChange: e => setTask(e.target.value) },
          ['synthetic-T', 'synthetic-U'].map(id => React.createElement('option', { key: id }, id)))),
      React.createElement(ForensicReportPage, { scopeType: 'task', scopeId: task, generationPollIntervalMs: 80,
        requestedReportId: query.get('report_id'), onVersionChange: report_id => setQuery({ report_id }) }));
}
createRoot(document.getElementById('root')).render(React.createElement(MemoryRouter,
  { initialEntries: [location.pathname + location.search] }, React.createElement(Harness)));
`;
const server = await createServer({
  root: webRoot, configFile: false, envFile: false, envDir: false,
  envPrefix: '__REPORT_BROWSER_TEST_UNUSED_', logLevel: 'warn',
  define: {
    'import.meta.env.VITE_API_BASE_URL': '""',
    'import.meta.env.VITE_PYTHON_API_URL': '"/python"',
    'import.meta.env.VITE_FIELD_AUTH': '"disabled"',
  },
  server: { host: '127.0.0.1', port: 0, hmr: false, proxy: {} },
  plugins: [react(), {
    name: 'synthetic-report-harness',
    resolveId(id) { if (id === '/__report-test-entry.js') return '\0report-test-entry'; },
    load(id) { if (id === '\0report-test-entry') return entry; },
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url.split('?')[0] === '/__report-test.html') {
          res.setHeader('Content-Type', 'text/html');
          res.end(await vite.transformIndexHtml(req.url,
            '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/__report-test-entry.js"></script></html>'));
        } else if (/^\/(api|python|tasks|csapi)\b/.test(req.url)) {
          // Defense in depth: an interception mistake cannot proxy to host services.
          res.statusCode = 503;
          res.end('Synthetic interception required');
        } else next();
      });
    },
  }],
});
const text = '合成材料：付款安排待核。😀 此记录也可能属于正常业务。\n<img src=x onerror="window.__injected=true">';
const evidenceKey = 'file:/合成材料/往来记录😀.txt';
const missingKey = 'file:/合成材料/暂不可读.db';
const quote = { material_id: 'm0001', quote: '付款安排待核', character_start: 5, character_end: 11, ambiguous: false };
const direction = { direction_id: 'd1', title: '付款往来需要核查', description: '材料显示付款安排，但不足以确定活动性质。',
  finding_kind: 'hypothesis', supporting_refs: [quote], counter_refs: [], missing_information: ['原始业务凭据'],
  alternative_explanations: ['正常业务往来'], baseline_direction_ids: [], origin: 'material', case_context_quote: '' };
function report(id, version, mode = 'evidence_only', task = 'synthetic-T') {
  const guided = mode === 'case_guided';
  return {
    task_id: task, report_id: id, version, status: 'ready', title: `合成报告 ${id}`,
    created_at: '2026-10-20T01:00:00Z', model: 'synthetic-model', generation_id: `g-${id}`, input_hash: 'a'.repeat(64),
    prompt_version: `final-report:${mode}:v1`,
    citations: [{ citation_id: 'c001', evidence_key: evidenceKey }, { citation_id: 'c002', evidence_key: missingKey },
      { citation_id: 'c003', evidence_key: evidenceKey }],
    sections: [{ heading: '材料观察', content: '往来记录😀.txt 记载付款安排；需要核对原始凭据。', citation_ids: ['c001'] }],
    evidence_classifications: { questions: [{ question_id: 'q1', text: '付款事实是否完整？', origin: 'generic' }],
      items: [
        { evidence_key: evidenceKey, material_type: 'chat_record', topics: ['funds', 'communications'],
          priority: guided ? 'P1' : 'P2', material_states: ['deleted'], review_status: 'pending',
          reason: '涉及付款安排，金额尚需进一步核对。', basis_type: 'neutral_material', basis_quote: quote.quote,
          relations: [{ question_id: 'q1', relation: 'supports', reason: '材料记载需要核对' }] },
        { evidence_key: missingKey, material_type: 'document', topics: [], priority: 'unassessed',
          material_states: ['insufficient_content', 'incomplete_provenance'], review_status: 'machine_suggested',
          reason: '内容不可读，不能评估。', basis_type: 'metadata', relations: [] },
      ] },
    stage_analysis: mode === 'legacy' ? null : {
      analysis_mode: mode, evidence_scope_hash: 'b'.repeat(64), case_description: guided ? '合成案情：待核诈骗及资金流向。' : '',
      baseline_report_id: guided ? 'report-a' : null, baseline_report_hash: guided ? 'c'.repeat(64) : null,
      materials: [
        { material_id: 'm0001', evidence_key: evidenceKey, kind: 'text', text, original_characters: Array.from(text).length,
          source_sha256: 'd'.repeat(64), content_sha256: 'e'.repeat(64), status: 'partial', limitations: ['FIRST_4000_PARSED_CHARACTERS_ONLY'] },
        { material_id: 'm0002', evidence_key: missingKey, kind: 'unavailable', text: '', original_characters: 0,
          source_sha256: '', content_sha256: 'f'.repeat(64), status: 'unavailable', limitations: ['SOURCE_UNAVAILABLE'] },
      ],
      directions: guided ? [direction, { ...direction, direction_id: 'd2', title: '案情提出的另一种假设',
        supporting_refs: [], origin: 'case_only', case_context_quote: '待核诈骗' }] : [direction],
      comparisons: guided ? [{ baseline_direction_id: 'd1', status: 'insufficient', reason: '对照未完成，首次方向完整保留。',
        supporting_refs: [], counter_refs: [], missing_information: ['业务凭据'] }] : [],
      baseline_directions: guided ? [direction] : [], baseline_priorities: guided ? { [evidenceKey]: 'P2' } : {},
      warnings: guided ? ['COMPARISON_REJECTED', 'TEXT_MODEL_CHANGED_OR_BASELINE_MODEL_UNKNOWN'] : [],
      text_models: ['synthetic-new'], baseline_text_models: guided ? ['synthetic-old'] : [],
    },
  };
}
const row = r => ({ report_id: r.report_id, version: r.version, status: 'ready', report_kind: 'llm_generation', title: r.title });
const gate = () => {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release };
};
const until = async (condition, label) => {
  const end = Date.now() + 8000;
  while (!condition()) {
    if (Date.now() > end) throw new Error(`Timed out: ${label}`);
    await new Promise(resolve => setTimeout(resolve, 20));
  }
};
const submitSelector = '[data-testid="generate-submit"]';
const actorSelector = '[data-testid="generate-actor-input"]';
const inputSelector = 'textarea[aria-label="本次案情描述"]';
const versionSelector = n => `input[aria-label="版本 ${n}"]`;
async function replace(page, selector, value) {
  await page.focus(selector);
  await page.keyboard.down('Control');
  await page.keyboard.press('KeyA');
  await page.keyboard.up('Control');
  await page.keyboard.press('Backspace');
  await page.keyboard.sendCharacter(value);
}
async function bodyContains(page, value) {
  await page.waitForFunction(value => document.body.innerText.includes(value), {}, value);
}
async function selectVersion(page, n) {
  await page.click(versionSelector(n));
  await page.waitForFunction(selector => document.querySelector(selector)?.checked, {}, versionSelector(n));
}
async function openDetails(page, label) {
  const summary = await page.waitForSelector(`::-p-text(${label})`);
  await summary.click();
}
let browser;
const results = { mode: 'SYNTHETIC_UI_ONLY', browser: '', started_at: new Date().toISOString(), scenarios: [], output };
async function fixture(initial = [report('report-a', 1)], options = {}) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  await page.setViewport({ width: 1440, height: 1000 });
  await page.setBypassServiceWorker(true);
  const state = {
    versions: initial.map(row), reports: Object.fromEntries(initial.map(r => [r.report_id, r])),
    requests: [], errors: [], unexpected: [], posts: [], generations: {}, gates: [],
    taskDescription: '保存的合成案情，不得进入首次请求。', ...options,
  };
  state.hold = () => { const held = gate(); state.gates.push(held); return held; };
  state.publish = r => { state.reports[r.report_id] = r; state.versions.push(row(r)); };
  state.complete = (r, id = state.lastGeneration) => {
    state.publish(r);
    state.generations[id] = { ...state.generations[id], status: 'completed', report_id: r.report_id, produced_version: r.version };
  };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      if (request.url().startsWith('data:')) { await request.continue(); return; }
      const url = new URL(request.url());
      if (url.origin !== origin) {
        state.unexpected.push(request.url());
        await request.abort();
        return;
      }
      const pathname = url.pathname.replace(/^\/python(?=\/)/, '');
      if (!pathname.startsWith('/api/')) {
        if (['document', 'script', 'stylesheet', 'font', 'image', 'other'].includes(request.resourceType())) await request.continue();
        else { state.unexpected.push(request.url()); await request.abort(); }
        return;
      }
      const data = request.postData() ? JSON.parse(request.postData()) : null;
      const record = { method: request.method(), path: pathname, query: Object.fromEntries(url.searchParams), data };
      state.requests.push(record);
      const respond = (body, status = 200) => request.respond({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (state.override && await state.override(record, respond)) return;
      if (request.method() === 'GET' && pathname.startsWith('/api/tasks/')) {
        if (state.taskGate) await state.taskGate.promise;
        await respond({ task_id: pathname.split('/').pop(), case_description: state.taskDescription }); return;
      }
      if (request.method() === 'GET' && pathname === '/api/reports') {
        if (state.listGate) await state.listGate.promise;
        await respond(url.searchParams.get('scope_id') === 'synthetic-T' ? state.versions : []); return;
      }
      if (request.method() === 'GET' && pathname === '/api/reports/evidence') {
        await respond([{ evidence_key: evidenceKey, report_status: 'main' }, { evidence_key: missingKey, report_status: 'appendix' }]); return;
      }
      if (request.method() === 'GET' && pathname.startsWith('/api/reports/narrative/versions/')) {
        const id = decodeURIComponent(pathname.split('/').pop());
        const value = structuredClone(state.reports[id]);
        if (state.narrativeGates?.[id]) await state.narrativeGates[id].promise;
        await respond(value || { detail: 'Synthetic report missing' }, value ? 200 : 404); return;
      }
      if (request.method() === 'POST' && pathname === '/api/reports/generate') {
        state.posts.push(data);
        const number = state.posts.length;
        if (state.admissionGate) await state.admissionGate.promise;
        if (state.admissionError) { await respond({ detail: state.admissionError }, 409); return; }
        const id = `synthetic-generation-${number}`;
        state.lastGeneration = id;
        state.generations[id] = { generation_id: id, task_id: data.task_id, status: 'running' };
        await respond(state.generations[id], 202); return;
      }
      if (request.method() === 'GET' && pathname.startsWith('/api/reports/generations/')) {
        const id = pathname.split('/').pop();
        if (state.pollGate) await state.pollGate.promise;
        if (state.pollFailures) { state.pollFailures--; await respond({ detail: 'Synthetic transient failure' }, 503); return; }
        await respond(state.generations[id]); return;
      }
      state.unexpected.push(record);
      await respond({ detail: 'Unexpected synthetic request' }, 500);
    } catch (error) {
      if (!page.isClosed()) state.errors.push(error.message);
    }
  });
  await page.goto(`${origin}/__report-test.html${state.requestedReportId ? `?report_id=${encodeURIComponent(state.requestedReportId)}` : ''}`, { waitUntil: 'networkidle0' });
  await page.waitForSelector(submitSelector);
  return {
    page, state,
    async start() {
      await replace(page, actorSelector, '合成分析人');
      await page.click(submitSelector);
      await until(() => state.posts.length > 0, 'admission request');
    },
    async close() {
      state.gates.forEach(g => g.release());
      await context.close();
    },
  };
}
let origin;
async function test(name, run, initial, options) {
  if (process.env.REPORT_BROWSER_FILTER && !name.includes(process.env.REPORT_BROWSER_FILTER)) return;
  let f;
  const started = Date.now();
  try {
    f = await fixture(initial, options);
    await run(f);
    assert.deepEqual(f.state.errors, [], 'browser page/runtime errors');
    assert.deepEqual(f.state.unexpected, [], 'unexpected requests');
    results.scenarios.push({ name, status: 'PASS', duration_ms: Date.now() - started, requests: f.state.requests.length });
    console.log(`PASS ${name}`);
  } catch (error) {
    const screenshot = path.join(output, `${results.scenarios.length + 1}-failed.png`);
    if (f) await f.page.screenshot({ path: screenshot, fullPage: true }).catch(() => {});
    const overflowing = f ? await f.page.evaluate(() => [...document.querySelectorAll('body *')]
      .filter(e => e.getClientRects().length && e.getBoundingClientRect().right > innerWidth + 1)
      .slice(0, 12).map(e => ({ tag: e.tagName, class: e.className, text: e.textContent.slice(0, 100), width: e.getBoundingClientRect().width }))) : [];
    results.scenarios.push({ name, status: 'FAIL', error: error.stack, screenshot, page_errors: f?.state.errors, unexpected: f?.state.unexpected, overflowing });
    console.log(`FAIL ${name}: ${error.message}`);
  } finally { await f?.close(); }
}
try {
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await puppeteer.launch({ executablePath: browserPath, headless: true,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run'] });
  results.browser = await browser.version();
  await test('first completion opens exact report, even if another newer version exists', async f => {
    await f.start();
    assert.deepEqual(f.state.posts[0], { task_id: 'synthetic-T', requested_by: '合成分析人', analysis_mode: 'evidence_only' });
    f.state.publish(report('unrelated-newer', 2));
    f.state.complete(report('report-a', 1));
    await f.page.waitForSelector(versionSelector(2));
    await f.page.waitForFunction(s => document.querySelector(s)?.checked, {}, versionSelector(1));
    await bodyContains(f.page, '合成报告 report-a');
  }, []);

  await test('stage A to B submits exact baseline/context and preserves both versions', async f => {
    const before = structuredClone(f.state.reports['report-a']);
    await f.page.click('input[value="case_guided"]');
    await bodyContains(f.page, '基于首次报告 report-a');
    await replace(f.page, inputSelector, '本轮修订：诈骗与洗钱均为待核假设😀');
    await f.start();
    assert.deepEqual(f.state.posts[0], { task_id: 'synthetic-T', requested_by: '合成分析人',
      analysis_mode: 'case_guided', base_report_id: 'report-a', case_description: '本轮修订：诈骗与洗钱均为待核假设😀' });
    f.state.complete(report('report-b', 2, 'case_guided'));
    await f.page.waitForSelector('[data-testid="baseline-report-link"]');
    assert.equal(await f.page.$eval('[data-testid="baseline-report-link"]', el => el.getAttribute('href')),
      '/case-intelligence?task_id=synthetic-T&tab=forensic&report_id=report-a');
    await bodyContains(f.page, '基于首次报告 report-a');
    await selectVersion(f.page, 1);
    await bodyContains(f.page, '首次自主研判 · 材料发现');
    assert.deepEqual(f.state.reports['report-a'], before);
    assert.equal(f.state.requests.filter(r => r.method !== 'GET').length, 1);
  });

  await test('generation from a report deep link opens its new result and updates route identity', async f => {
    await bodyContains(f.page, '合成报告 report-a');
    await f.page.click('input[value="case_guided"]');
    await bodyContains(f.page, '基于首次报告 report-a');
    await f.start();
    f.state.complete(report('report-b', 2, 'case_guided'));
    await f.page.waitForSelector(versionSelector(2));
    await f.page.waitForSelector('[data-testid="baseline-report-link"]');
    assert.equal(await f.page.$eval('[data-testid="test-route"]', e => e.textContent), 'report_id=report-b');
  }, undefined, { requestedReportId: 'report-a' });

  await test('legacy baseline / missing actor / empty context are blocked', async f => {
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), true);
    await f.page.click('input[value="case_guided"]');
    await replace(f.page, actorSelector, '合成分析人');
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), true);
    await selectVersion(f.page, 1);
    await bodyContains(f.page, '基于首次报告 report-a');
    await replace(f.page, inputSelector, '   ');
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), true);
    assert.equal(f.state.posts.length, 0);
  }, [report('report-a', 1), report('legacy', 2, 'legacy')]);

  await test('oversized saved context is visible and blocked without truncation', async f => {
    await f.page.click('input[value="case_guided"]');
    await bodyContains(f.page, '已保存案情超过本轮8000字限制');
    assert.equal(await f.page.$eval(inputSelector, e => e.value.length), 8100);
    await replace(f.page, actorSelector, '合成分析人');
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), true);
    await replace(f.page, inputSelector, '缩减后的合成案情');
    await f.page.waitForFunction(s => !document.querySelector(s).disabled, {}, submitSelector);
  }, undefined, { taskDescription: '案'.repeat(8100) });

  await test('rapid double click creates only one generation', async f => {
    f.state.admissionGate = f.state.hold();
    await replace(f.page, actorSelector, '合成分析人');
    await f.page.$eval(submitSelector, e => { e.click(); e.click(); });
    await until(() => f.state.posts.length === 1, 'one admission');
    f.state.admissionGate.release();
    await f.page.waitForSelector('[data-testid="generate-status"]');
    assert.equal(f.state.posts.length, 1);
  });

  await test('409 admission rejection is actionable and can be retried', async f => {
    f.state.admissionError = { code: 'invalid_baseline' };
    await f.page.click('input[value="case_guided"]');
    await bodyContains(f.page, '基于首次报告 report-a');
    await f.start();
    await bodyContains(f.page, '历史案情报告不能冒充中立基线');
    f.state.admissionError = null;
    await f.page.click(submitSelector);
    await f.page.waitForSelector('[data-testid="generate-status"]');
    assert.equal(f.state.posts.length, 2);
  });

  await test('transient polling error recovers; durable failure requires explicit retry', async f => {
    f.state.pollFailures = 2;
    await f.start();
    await f.page.waitForSelector('[data-testid="generate-poll-error"]');
    await bodyContains(f.page, '生成中');
    f.state.generations[f.state.lastGeneration].status = 'failed';
    Object.assign(f.state.generations[f.state.lastGeneration],
      { error_code: 'neutral_sources_unavailable', error_message: 'Synthetic source unavailable' });
    await f.page.waitForSelector('[data-testid="generate-failed-detail"]');
    await bodyContains(f.page, '没有可用的中立材料');
    assert.equal(f.state.posts.length, 1);
    await f.page.click(submitSelector);
    await until(() => f.state.posts.length === 2, 'explicit retry');
    f.state.complete(report('retry-result', 2));
    await bodyContains(f.page, '合成报告 retry-result');
  });

  await test('historical selection during running generation remains selected', async f => {
    await f.start();
    await f.page.waitForSelector('[data-testid="generate-status"]');
    await selectVersion(f.page, 1);
    f.state.complete(report('report-new', 3));
    await f.page.waitForSelector(versionSelector(3));
    assert.equal(await f.page.$eval(versionSelector(1), e => e.checked), true);
  }, [report('report-a', 1), report('report-old', 2)]);

  await test('historical selection while admission is delayed remains selected', async f => {
    f.state.admissionGate = f.state.hold();
    await f.start();
    await selectVersion(f.page, 1);
    f.state.admissionGate.release();
    await f.page.waitForSelector('[data-testid="generate-status"]');
    f.state.complete(report('report-new', 3));
    await f.page.waitForSelector(versionSelector(3));
    await bodyContains(f.page, '已发布版本 report-new');
    assert.equal(await f.page.$eval(versionSelector(1), e => e.checked), true);
  }, [report('report-a', 1), report('report-old', 2)]);

  await test('historical selection during completion list refresh remains selected', async f => {
    await f.start();
    await f.page.waitForSelector('[data-testid="generate-status"]');
    const initialLists = f.state.requests.filter(r => r.path === '/api/reports').length;
    f.state.listGate = f.state.hold();
    f.state.complete(report('report-new', 3));
    await until(() => f.state.requests.filter(r => r.path === '/api/reports').length > initialLists, 'completion refresh');
    await selectVersion(f.page, 1);
    f.state.listGate.release();
    await bodyContains(f.page, '合成报告 report-a');
    // Wait for the held refresh to settle in the browser.
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$eval(versionSelector(1), e => e.checked), true);
  }, [report('report-a', 1), report('report-old', 2)]);

  await test('task switch during pending admission does not block the new task', async f => {
    f.state.admissionGate = f.state.hold();
    await f.start();
    await f.page.select('[aria-label="合成测试任务"]', 'synthetic-U');
    await bodyContains(f.page, '取证报告');
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), false);
    f.state.admissionGate.release();
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$('[data-testid="generate-status"]'), null);
  });

  await test('late report response cannot populate another task baseline or viewer', async f => {
    f.state.narrativeGates = { 'report-a': f.state.hold() };
    await selectVersion(f.page, 1);
    await f.page.waitForSelector('[data-testid="narrative-report-loading"]');
    await f.page.select('[aria-label="合成测试任务"]', 'synthetic-U');
    f.state.narrativeGates['report-a'].release();
    await f.page.click('input[value="case_guided"]');
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$('[data-testid="stage-analysis"]'), null);
    assert.equal(await f.page.$eval(submitSelector, e => e.disabled), true);
    assert.equal(await f.page.evaluate(() => document.body.innerText.includes('基于首次报告 report-a')), false);
  }, [report('report-a', 1), report('report-old', 2)]);

  await test('old admission cannot replace a newer task submission or unlock its pending button', async f => {
    const oldAdmission = f.state.hold();
    f.state.admissionGate = oldAdmission;
    await f.start();
    await f.page.select('[aria-label="合成测试任务"]', 'synthetic-U');
    await f.page.waitForFunction(s => !document.querySelector(s)?.disabled, {}, submitSelector);
    const newAdmission = f.state.hold();
    f.state.admissionGate = newAdmission;
    await f.page.click(submitSelector);
    await until(() => f.state.posts.length === 2, 'new task admission');
    oldAdmission.release();
    await until(() => f.state.generations['synthetic-generation-1'], 'old admission settled');
    await f.page.waitForFunction(s => document.querySelector(s)?.disabled, {}, submitSelector);
    assert.equal(await f.page.$('[data-testid="generate-status"]'), null);
    newAdmission.release();
    await bodyContains(f.page, 'synthetic-generation-2');
    assert.equal(f.state.posts[1].task_id, 'synthetic-U');
    assert.equal(f.state.requests.some(r => r.path.endsWith('/generations/synthetic-generation-1')), false);
  });

  await test('late completed poll cannot open an old report after switching tasks', async f => {
    f.state.pollGate = f.state.hold();
    await f.start();
    await until(() => f.state.requests.some(r => r.path.includes('/generations/')), 'pending poll');
    await f.page.select('[aria-label="合成测试任务"]', 'synthetic-U');
    f.state.complete(report('late-result', 2));
    f.state.pollGate.release();
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$('[data-testid="stage-analysis"]'), null);
    assert.equal(await f.page.$('[data-testid="generate-status"]'), null);
  });

  await test('late saved context cannot overwrite analyst typing', async f => {
    f.state.taskGate = f.state.hold();
    await f.page.select('[aria-label="合成测试任务"]', 'synthetic-U');
    await f.page.click('input[value="case_guided"]');
    await replace(f.page, inputSelector, '分析人员已输入的本轮描述');
    f.state.taskGate.release();
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$eval(inputSelector, e => e.value), '分析人员已输入的本轮描述');
  });

  await test('late same-task narrative response cannot replace a newly selected version', async f => {
    f.state.narrativeGates = { 'report-a': f.state.hold() };
    await selectVersion(f.page, 1);
    await f.page.waitForSelector('[data-testid="narrative-report-loading"]');
    await selectVersion(f.page, 2);
    await bodyContains(f.page, '合成报告 report-b');
    f.state.narrativeGates['report-a'].release();
    await f.page.waitForNetworkIdle({ idleTime: 100 });
    assert.equal(await f.page.$eval('[data-testid="narrative-report-view"] h2', e => e.textContent), '合成报告 report-b');
    await f.page.click('[data-testid="citation-chip-c001"]');
    await f.page.waitForSelector('[role="dialog"]');
    await f.page.keyboard.press('Escape');
    await selectVersion(f.page, 1);
    await bodyContains(f.page, '首次自主研判 · 材料发现');
    assert.equal(await f.page.$('[role="dialog"]'), null);
  }, [report('report-a', 1), report('report-b', 2, 'case_guided')]);

  await test('frozen source hover/drawer/backlink and escaped untrusted text', async f => {
    await f.page.hover('[data-testid="citation-chip-c001"]');
    await bodyContains(f.page, '本轮冻结材料片段');
    await f.page.click('[data-testid="citation-chip-c001"]');
    await f.page.waitForSelector('[role="dialog"]');
    assert.equal(await f.page.$eval('[aria-label="本轮冻结材料溯源"] pre', e => e.textContent), text);
    assert.equal(await f.page.evaluate(() => window.__injected), undefined);
    const link = new URL(await f.page.$eval('[role="dialog"] a', e => e.href));
    assert.equal(link.searchParams.get('report_id'), 'report-a');
    assert.equal(link.searchParams.get('citation_id'), 'c001');
    await f.page.keyboard.press('Escape');
    await f.page.waitForSelector('[role="dialog"]', { hidden: true });
    assert.equal(f.state.requests.some(r => r.path.includes('/investigation/evidence/snapshot')), false);
  });

  await test('source dialog traps keyboard focus and restores it on Escape', async f => {
    const marker = '[data-testid="citation-chip-c001"]';
    await f.page.focus(marker);
    await f.page.keyboard.press('Enter');
    await f.page.waitForSelector('[role="dialog"]');
    await f.page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'dialog');
    await f.page.keyboard.down('Shift');
    await f.page.keyboard.press('Tab');
    await f.page.keyboard.up('Shift');
    assert.equal(await f.page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), true);
    for (let i = 0; i < 5; i++) {
      await f.page.keyboard.press('Tab');
      assert.equal(await f.page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), true);
    }
    await f.page.keyboard.press('Escape');
    await f.page.waitForSelector('[role="dialog"]', { hidden: true });
    assert.equal(await f.page.$eval(marker, e => e === document.activeElement), true);
  });

  await test('classification filters keep narrative and count unique materials', async f => {
    await bodyContains(f.page, '证据分类 · 2 份材料');
    const narrative = await f.page.$eval('[data-testid="narrative-sections"]', e => e.innerText);
    await openDetails(f.page, '查看分类材料与依据');
    await f.page.select('select[aria-label="筛选核查优先级"]', 'P1');
    await bodyContains(f.page, '没有符合当前条件的材料');
    assert.equal(await f.page.$eval('[data-testid="narrative-sections"]', e => e.innerText), narrative);
    await f.page.select('select[aria-label="筛选核查优先级"]', 'all');
    await f.page.select('select[aria-label="筛选业务主题"]', 'funds');
    assert.equal((await f.page.$$('[data-testid="classified-evidence"]')).length, 1);
    const neutral = await f.page.$eval('[data-testid="priority-count-unassessed"]', e => getComputedStyle(e).borderStyle);
    assert.equal(neutral, 'dashed');
  });

  await test('comparison failure, baseline findings, priority changes, unavailable materials remain visible', async f => {
    await bodyContains(f.page, '对照未完成，首次方向完整保留。');
    await bodyContains(f.page, '仅案情提出，尚无材料支持');
    await bodyContains(f.page, '判断差异不能全部归因于案情变化');
    await openDetails(f.page, '保留首次自主发现');
    await openDetails(f.page, '核查优先级变化');
    await bodyContains(f.page, '首次：P2 重点关注 → 本轮：P1 优先核查');
    await openDetails(f.page, '读取范围与未完成项');
    await f.page.click('button::-p-text(m0002)');
    await bodyContains(f.page, '本次没有可用内容');
    await f.page.click('[aria-label="关闭溯源面板"]');
    await f.page.waitForSelector('[role="dialog"]', { hidden: true });
  }, [report('report-a', 1), report('report-b', 2, 'case_guided')]);

  await test('desktop/mobile 320px/390px and dark theme have no horizontal overflow', async f => {
    await bodyContains(f.page, '二次研判与首次判断对照');
    for (const [width, dark] of [[1440, false], [390, false], [320, true]]) {
      await f.page.setViewport({ width, height: 1000 });
      await f.page.evaluate(dark => { document.documentElement.classList.toggle('dark', dark); }, dark);
      await openDetails(f.page, '查看本次冻结案情');
      const dimensions = await f.page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
      assert.ok(dimensions.scroll <= dimensions.width + 1, `overflow at ${width}px: ${JSON.stringify(dimensions)}`);
      await f.page.screenshot({ path: path.join(output, `report-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true });
      await f.page.click('[data-testid="citation-chip-c001"]');
      await f.page.waitForSelector('[role="dialog"]');
      assert.equal(await f.page.$eval('[data-testid="citation-overlay"]', e => {
        const bounds = e.getBoundingClientRect();
        return bounds.top === 0 && bounds.left === 0 && bounds.right === innerWidth && bounds.bottom === innerHeight;
      }), true, `overlay must cover the viewport at ${width}px`);
      assert.ok(await f.page.$eval('[role="dialog"]', e => e.scrollWidth <= e.clientWidth + 1), `drawer overflow at ${width}px`);
      await f.page.screenshot({ path: path.join(output, `source-${width}-${dark ? 'dark' : 'light'}.png`) });
      await f.page.keyboard.press('Escape');
      await f.page.waitForSelector('[role="dialog"]', { hidden: true });
    }
  }, [report('report-a', 1), report('report-b', 2, 'case_guided')]);

  const longReport = report('report-long', 1, 'case_guided');
  const longToken = 'https://synthetic.invalid/' + '路径😀资金'.repeat(25) + 'unbroken-account-reference-'.repeat(15);
  longReport.title = longToken;
  longReport.stage_analysis.case_description = longToken;
  longReport.stage_analysis.directions[0].description = longToken;
  await test('long mixed Unicode paths and unbroken identifiers wrap on 320px screens', async f => {
    await f.page.setViewport({ width: 320, height: 900 });
    await openDetails(f.page, '查看本次冻结案情');
    const dimensions = await f.page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
    assert.ok(dimensions.scroll <= dimensions.width + 1, `long content overflow: ${JSON.stringify(dimensions)}`);
  }, [longReport]);
} finally {
  await browser?.close();
  await server.close();
  results.finished_at = new Date().toISOString();
  results.passed = results.scenarios.filter(t => t.status === 'PASS').length;
  results.failed = results.scenarios.filter(t => t.status === 'FAIL').length;
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(`Results: ${results.passed} passed, ${results.failed} failed. ${path.join(output, 'results.json')}`);
}
if (results.failed) process.exitCode = 1;
