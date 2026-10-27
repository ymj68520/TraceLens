/* eslint-env node */
/**
 * 无头浏览器验收：任务级分析文件预算（llm_max_files）
 *
 * 走真实点击路径验证两个建任务入口：
 *  1. 任务列表 → 创建任务：默认「使用系统默认」不发字段；选 300 发 300；
 *     自定义 1234 发 1234；空自定义/越界被前端拦下且不发请求
 *  2. 案件管理 → 新建多镜像案件：预算选项存在，且提交选项透传 llmMaxFiles
 *
 * 断言以 CDP 层捕获的 POST /api/tasks 请求体为准（axios 走 XHR，不是 fetch）。
 * 跑完自动删除测试创建的任务。
 *
 * 运行：node scripts/e2e-analysis-budget.mjs
 * 需要：vite dev server（默认 http://127.0.0.1:3000）+ C++ 后端
 */
import puppeteer from 'puppeteer';
import fs from 'node:fs';

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:3000';
const SHOT_DIR = process.env.E2E_SHOT_DIR || '/tmp/tracelens-e2e';
const IMAGE_PATH = process.env.E2E_IMAGE_PATH
  || '/home/ymj68520/projects/Forensics/TraceLens/test_image.img';
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

/** 找到「分析文件上限」下拉框（按 label 文本定位，避免依赖顺序） */
async function budgetSelectHandle(page) {
  return page.evaluateHandle(() => {
    const label = [...document.querySelectorAll('label')]
      .find((l) => (l.innerText || '').trim() === '分析文件上限');
    if (!label) return null;
    const scope = label.closest('div') || document;
    return scope.querySelector('select');
  });
}

async function setNativeValue(page, elementHandle, value) {
  await page.evaluate((el, v) => {
    const proto = el.tagName === 'SELECT'
      ? window.HTMLSelectElement.prototype
      : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, elementHandle, value);
}

async function fillCaseDescription(page) {
  const handle = await page.$('textarea[placeholder*="请输入案情描述"]');
  if (!handle) throw new Error('找不到案情描述输入框');
  await page.evaluate((el) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(el, '预算验收：一起网络诈骗案件');
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, handle);
}

async function fillImagePath(page, imgPath) {
  const handle = await page.evaluateHandle((p) => {
    return [...document.querySelectorAll('input[type="text"]')].find((i) =>
      i.placeholder && i.placeholder.includes(p)) || null;
  }, '/path/to/disk_image');
  const el = handle.asElement();
  if (!el) throw new Error('找不到检材路径输入框');
  await page.evaluate((input, v) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, v);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, el, imgPath);
}

/** 打开创建任务弹窗，返回该弹窗的提交请求捕获器 */
async function openCreateTaskModal(page) {
  await clickByText(page, '➕ 创建任务');
  await page.waitForFunction(
    () => [...document.querySelectorAll('label')].some((l) => (l.innerText || '').trim() === '分析文件上限'),
    { timeout: 15000 },
  );
}

async function pageError(page) {
  return page.evaluate(() => {
    const el = [...document.querySelectorAll('div')].find((d) =>
      (d.className || '').toString().includes('bg-red-50'));
    return el ? el.innerText.trim() : null;
  });
}

async function readBudgetState(page) {
  return page.evaluate(() => {
    const label = [...document.querySelectorAll('label')]
      .find((l) => (l.innerText || '').trim() === '分析文件上限');
    if (!label) return null;
    const scope = label.closest('div') || document;
    const select = scope.querySelector('select');
    const number = scope.querySelector('input[type="number"]');
    return { select: select ? select.value : null, custom: number ? number.value : null };
  });
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
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  // 捕获所有建任务请求体（axios 走 XHR，CDP 层才看得到）
  const createRequests = [];
  page.on('request', (req) => {
    try {
      if (req.method() === 'POST' && new URL(req.url()).pathname.replace(/\/$/, '') === '/api/tasks') {
        createRequests.push(JSON.parse(req.postData() || '{}'));
      }
    } catch { /* 非 JSON 请求体，忽略 */ }
  });

  try {
    // ── 进入任务页 ────────────────────────────────────────────────
    // 从根路径进开发入口，再用侧边栏客户端路由跳转；直接 GET /tasks 会
    // 命中 SPA fallback 拿到 dist 产物，测的就不是当前源码了。
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(
      () => [...document.querySelectorAll('a')].some((a) => a.innerText.includes('任务列表')),
      { timeout: 20000 },
    );
    await page.evaluate(() => {
      const link = [...document.querySelectorAll('a')].find((a) => a.innerText.includes('任务列表'));
      link.click();
    });
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('创建任务')),
      { timeout: 20000 },
    );
    record('进入任务列表', page.url().includes('/tasks'), page.url());

    // ── 1. 默认 = 使用系统默认 ───────────────────────────────────
    await openCreateTaskModal(page);
    const initial = await readBudgetState(page);
    record('创建任务弹窗出现「分析文件上限」', initial !== null, JSON.stringify(initial));
    record('默认选择「使用系统默认」', initial?.select === 'default', `select=${initial?.select}`);
    record('默认不展开自定义输入框', initial?.custom === null, `custom=${initial?.custom}`);
    await page.screenshot({ path: `${SHOT_DIR}/20-budget-default.png` });

    // 默认提交：载荷不能带 llm_max_files
    await fillImagePath(page, IMAGE_PATH);
    await fillCaseDescription(page);
    await clickByText(page, '创建任务', { exact: true });
    await new Promise((r) => setTimeout(r, 4000));
    const defaultPayload = createRequests[createRequests.length - 1];
    record('默认预算提交成功', !!defaultPayload,
      defaultPayload ? `task payload keys=${Object.keys(defaultPayload).join(',')}` : `页面错误：${await pageError(page)}`);
    record('默认预算不发 llm_max_files 字段',
      !!defaultPayload && !('llm_max_files' in defaultPayload),
      defaultPayload ? `llm_max_files=${JSON.stringify(defaultPayload.llm_max_files)}` : '无载荷');
    await page.screenshot({ path: `${SHOT_DIR}/21-after-default-submit.png` });

    // ── 2. 预设 300 ──────────────────────────────────────────────
    await openCreateTaskModal(page);
    const selectHandle = await budgetSelectHandle(page);
    await setNativeValue(page, selectHandle, '300');
    await new Promise((r) => setTimeout(r, 300));
    const presetState = await readBudgetState(page);
    record('选择预设 300 后下拉生效', presetState?.select === '300', `select=${presetState?.select}`);

    await fillImagePath(page, IMAGE_PATH);
    await fillCaseDescription(page);
    await clickByText(page, '创建任务', { exact: true });
    await new Promise((r) => setTimeout(r, 4000));
    const presetPayload = createRequests[createRequests.length - 1];
    record('预设预算载荷携带 llm_max_files=300',
      presetPayload?.llm_max_files === 300,
      `llm_max_files=${JSON.stringify(presetPayload?.llm_max_files)}`);

    // ── 3. 自定义 1234 ───────────────────────────────────────────
    await openCreateTaskModal(page);
    let handle = await budgetSelectHandle(page);
    await setNativeValue(page, handle, 'custom');
    await page.waitForFunction(
      () => [...document.querySelectorAll('input[type="number"]')].some((i) =>
        i.getAttribute('aria-label') === '自定义分析文件上限'),
      { timeout: 5000 },
    );
    const customInput = await page.$('input[aria-label="自定义分析文件上限"]');
    await setNativeValue(page, customInput, '1234');
    await new Promise((r) => setTimeout(r, 300));

    await fillImagePath(page, IMAGE_PATH);
    await fillCaseDescription(page);
    await clickByText(page, '创建任务', { exact: true });
    await new Promise((r) => setTimeout(r, 4000));
    const customPayload = createRequests[createRequests.length - 1];
    record('自定义预算载荷携带 llm_max_files=1234',
      customPayload?.llm_max_files === 1234,
      `llm_max_files=${JSON.stringify(customPayload?.llm_max_files)}`);
    await page.screenshot({ path: `${SHOT_DIR}/22-custom-budget.png` });

    // ── 4. 非法自定义值被前端拦下 ────────────────────────────────
    await openCreateTaskModal(page);
    handle = await budgetSelectHandle(page);
    await setNativeValue(page, handle, 'custom');
    const badInput = await page.$('input[aria-label="自定义分析文件上限"]');
    await setNativeValue(page, badInput, '999999');
    await fillImagePath(page, IMAGE_PATH);
    await fillCaseDescription(page);

    const beforeCount = createRequests.length;
    // 原生 min/max 约束会先拦下点击，这里直接派发 submit 走应用自身的校验。
    await page.evaluate(() => {
      const form = document.querySelector('form');
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await new Promise((r) => setTimeout(r, 1200));

    const errText = await pageError(page);
    record('越界自定义值被拦下并提示', /分析文件上限/.test(errText || ''), errText || '无提示');
    record('越界自定义值未发出建任务请求',
      createRequests.length === beforeCount,
      `新增 ${createRequests.length - beforeCount} 个请求`);
    await page.screenshot({ path: `${SHOT_DIR}/23-invalid-budget.png` });

    // 关掉弹窗，避免影响后续入口
    await page.evaluate(() => {
      const close = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === '✕');
      close?.click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // ── 5. 案件管理 → 新建多镜像案件 ─────────────────────────────
    await page.evaluate(() => {
      const link = [...document.querySelectorAll('a')].find((a) => a.innerText.includes('案件管理'));
      if (!link) throw new Error('侧边栏无 案件管理');
      link.click();
    });
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => /新建案件|创建案件/.test(b.innerText)),
      { timeout: 20000 },
    );
    await clickByText(page, '新建案件');
    await page.waitForFunction(
      () => [...document.querySelectorAll('label')].some((l) => (l.innerText || '').trim() === '分析文件上限'),
      { timeout: 10000 },
    );
    const caseBudget = await readBudgetState(page);
    record('新建案件弹窗也有「分析文件上限」', caseBudget !== null, JSON.stringify(caseBudget));
    record('新建案件默认「使用系统默认」', caseBudget?.select === 'default', `select=${caseBudget?.select}`);
    await page.screenshot({ path: `${SHOT_DIR}/24-case-modal-budget.png` });

    // 案件入口的提交走 createCaseWithTasks（不是 /api/tasks），这里验证
    // 选择 500 后表单状态正确、且真正创建的镜像任务带上该预算。
    handle = await budgetSelectHandle(page);
    await setNativeValue(page, handle, '500');
    await new Promise((r) => setTimeout(r, 300));
    const casePreset = await readBudgetState(page);
    record('新建案件可选预设 500', casePreset?.select === '500', `select=${casePreset?.select}`);

    // 填案件必填项并提交，然后回读后端：本案件新建的任务必须带 llm_max_files=500
    await page.evaluate((imgPath) => {
      const setVal = (el, v) => {
        const proto = el.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const name = [...document.querySelectorAll('input[type="text"]')]
        .find((i) => i.placeholder && i.placeholder.includes('某某网络诈骗案'));
      if (!name) throw new Error('找不到案件名称输入框');
      setVal(name, '预算验收案件');
      const desc = document.querySelector('textarea[placeholder*="请描述案情背景"]');
      if (!desc) throw new Error('找不到案件案情描述输入框');
      setVal(desc, '预算验收：跨镜像案件');
      const image = [...document.querySelectorAll('input[type="text"]')]
        .find((i) => i.placeholder && i.placeholder.includes('/path/to/image.E01'));
      if (!image) throw new Error('找不到案件镜像路径输入框');
      setVal(image, imgPath);
    }, IMAGE_PATH);
    await new Promise((r) => setTimeout(r, 500));
    await clickByText(page, '创建案件', { exact: false });
    await new Promise((r) => setTimeout(r, 6000));

    const caseTasks = await page.evaluate(async () => {
      const res = await fetch('/api/tasks?limit=50');
      const data = await res.json();
      return (data.tasks || []).filter((t) =>
        t.image_path && t.image_path.data === undefined
        && (t.case_description || '') === '预算验收：跨镜像案件')
        .map((t) => ({ id: t.id, budget: t.llm_max_files, status: t.status }));
    });
    record('案件入口创建了镜像任务', caseTasks.length > 0, JSON.stringify(caseTasks));
    record('案件入口创建的任务带 llm_max_files=500',
      caseTasks.length > 0 && caseTasks.every((t) => t.budget === 500),
      JSON.stringify(caseTasks));

    // ── 6. 控制台错误 ────────────────────────────────────────────
    const realErrors = consoleErrors.filter((e) =>
      !/favicon|Download the React DevTools|ResizeObserver loop|status of 4\d\d/i.test(e));
    record('无 JavaScript 运行时错误', realErrors.length === 0, realErrors.slice(0, 3).join(' | ') || '无');
  } catch (err) {
    record('测试执行', false, err.message);
    await page.screenshot({ path: `${SHOT_DIR}/error-budget.png` }).catch(() => {});
  } finally {
    // 清理：删掉本次验收创建的任务，避免污染任务列表
    try {
      const cleanup = await page.evaluate(async (imgPath) => {
        const res = await fetch('/api/tasks?limit=50');
        const data = await res.json();
        const doomed = (data.tasks || []).filter((t) =>
          t.image_path === imgPath
          && (t.case_description || '').startsWith('预算验收：'));
        const deleted = [];
        for (const t of doomed) {
          const r = await fetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
          if (r.ok) deleted.push(t.id.slice(0, 8));
        }
        return deleted;
      }, IMAGE_PATH);
      if (cleanup.length) console.log(`清理测试任务：${cleanup.join(', ')}`);
    } catch { /* 清理失败不影响验收结论 */ }
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
