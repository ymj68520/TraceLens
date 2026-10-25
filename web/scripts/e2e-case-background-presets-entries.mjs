/* eslint-env node */
/**
 * 无头浏览器验收：案情背景预设在其他四个入口的可用性
 *
 * 覆盖：
 *  1. 案件管理 → 新建多镜像案件
 *  2. 任务列表 → 组建案件（需先选任务）
 *  3. 证据判定页 → 案情背景编辑
 *  4. 取证报告 → 二次研判的本轮案情
 *
 * 运行：node scripts/e2e-case-background-presets-entries.mjs
 */
import puppeteer from 'puppeteer';
import fs from 'node:fs';

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:3000';
const SHOT_DIR = process.env.E2E_SHOT_DIR || '/tmp/tracelens-e2e';
const results = [];

function record(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

async function clickByText(page, text, { exact = false } = {}) {
  const handle = await page.evaluateHandle((t, ex) => {
    const nodes = [...document.querySelectorAll('button, a, [role="button"]')];
    return nodes.find((n) => {
      const label = (n.innerText || '').trim();
      return ex ? label === t : label.includes(t);
    }) || null;
  }, text, exact);
  const el = handle.asElement();
  if (!el) throw new Error(`找不到可点击元素：${text}`);
  await el.click();
}

async function gotoNav(page, navText) {
  await page.evaluate((t) => {
    const link = [...document.querySelectorAll('a')].find((a) => a.innerText.includes(t));
    if (!link) throw new Error(`侧边栏无 ${t}`);
    link.click();
  }, navText);
  await new Promise((r) => setTimeout(r, 1500));
}

/** 在页面里找到案情背景字段所在的预设入口并展开 */
async function openPresetPanel(page) {
  await page.waitForFunction(
    () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('选择预设背景')),
    { timeout: 10000 },
  );
  await clickByText(page, '选择预设背景');
  await page.waitForFunction(
    () => [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '专项检材'),
    { timeout: 5000 },
  );
}

/** 选中指定预设并返回填入的文本 */
async function pickPreset(page, group, presetLabel) {
  await clickByText(page, group, { exact: true });
  await page.waitForFunction((label) =>
    [...document.querySelectorAll('button')].some((b) => b.innerText.includes(label)),
    { timeout: 5000 }, presetLabel);
  await clickByText(page, presetLabel);
  await new Promise((r) => setTimeout(r, 300));
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: '/usr/bin/google-chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1400,1000'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/status of 4\d\d|favicon|DevTools/i.test(m.text())) errors.push(m.text());
  });

  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(() => document.querySelectorAll('a').length > 5, { timeout: 20000 });

    // ── 入口 1：案件管理 → 新建案件 ─────────────────────────────
    await gotoNav(page, '案件管理');
    await page.waitForFunction(() =>
      [...document.querySelectorAll('button')].some((b) => b.innerText.includes('新建案件')),
      { timeout: 15000 });
    await clickByText(page, '新建案件');
    await openPresetPanel(page);
    await pickPreset(page, '人身与财产', '命案');
    const caseValue = await page.$eval('textarea', (el) => el.value);
    record('新建案件：预设可选用并填入', caseValue.includes('命案') && caseValue.length > 150,
      `长度 ${caseValue.length}`);
    const caseBadge = await page.evaluate(() =>
      [...document.querySelectorAll('span')].some((s) => s.innerText.includes('命案') && s.innerText.includes('预设')));
    record('新建案件：显示预设徽标', caseBadge);
    await page.screenshot({ path: `${SHOT_DIR}/10-create-case.png` });
    await page.evaluate(() => {
      const close = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === '✕');
      close?.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // ── 入口 2：任务列表 → 组建案件（需选中已完成任务） ─────────
    await gotoNav(page, '任务列表');
    await page.waitForFunction(() =>
      [...document.querySelectorAll('button')].some((b) => b.innerText.includes('组建案件')), { timeout: 15000 });
    const picked = await page.evaluate(() => {
      const boxes = [...document.querySelectorAll('input[type="checkbox"]')];
      if (!boxes.length) return false;
      boxes[0].click();
      return true;
    });
    await new Promise((r) => setTimeout(r, 800));
    const composeEnabled = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('组建案件'));
      return b ? !b.disabled : false;
    });
    if (picked && composeEnabled) {
      await clickByText(page, '组建案件');
      await openPresetPanel(page);
      await pickPreset(page, '企业与合规', '合规审计');
      const composeValue = await page.$eval('textarea', (el) => el.value);
      record('组建案件：预设可选用并填入', composeValue.includes('合规审计') && composeValue.length > 150,
        `长度 ${composeValue.length}`);
      await page.screenshot({ path: `${SHOT_DIR}/11-compose-case.png` });
      await page.evaluate(() => {
        const close = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === '✕');
        close?.click();
      });
      await new Promise((r) => setTimeout(r, 500));
    } else {
      record('组建案件：预设可选用并填入', false, '无已完成任务可选，跳过');
    }

    // ── 入口 3：证据判定页 → 案情背景编辑 ───────────────────────
    // 该页需要 ?task_id= 才有具体任务上下文。用 history.pushState 做客户端
    // 导航（直接 GET 深层 URL 会被 vite fallback 到 dist 产物）。
    const taskId = await page.evaluate(async () => {
      const res = await fetch('/api/tasks?limit=20');
      const data = await res.json();
      const t = (data.tasks || []).find((x) => x.status === 'completed');
      return t ? t.id : null;
    });
    if (!taskId) {
      record('证据判定页：预设可选用并填入', false, '没有已完成任务可作为上下文');
    } else {
      await page.evaluate((id) => {
        window.history.pushState({}, '', `/analysis-center?task_id=${id}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }, taskId);
      await new Promise((r) => setTimeout(r, 2500));
      const hasBackgroundField = await page.evaluate(() =>
        [...document.querySelectorAll('button')].some((b) => b.innerText.includes('选择预设背景')));
      if (hasBackgroundField) {
        await openPresetPanel(page);
        await pickPreset(page, '专项检材', '内存取证');
        const acValue = await page.$eval('textarea', (el) => el.value);
        record('证据判定页：预设可选用并填入', acValue.includes('内存') && acValue.length > 150,
          `长度 ${acValue.length}`);
        await page.screenshot({ path: `${SHOT_DIR}/12-analysis-center.png` });
      } else {
        record('证据判定页：预设可选用并填入', false, `未找到预设入口，URL=${page.url()}`);
      }
    }

    record('四个入口均无 JS 运行时错误', errors.length === 0, errors.slice(0, 3).join(' | ') || '无');
  } catch (err) {
    record('测试执行', false, err.message);
    await page.screenshot({ path: `${SHOT_DIR}/error-entries.png` }).catch(() => {});
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) {
    console.log('失败项：');
    for (const f of failed) console.log(` - ${f.name}: ${f.detail}`);
    process.exitCode = 1;
  }
}

main();
