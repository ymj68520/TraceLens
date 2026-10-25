/* eslint-env node */
/**
 * 无头浏览器验收：案情背景预设
 *
 * 走真实点击路径：任务页 → 创建任务 → 展开预设面板 → 切换分组 → 选中预设
 * → 验证文本填入 → 手动改动 → 验证回退自定义 → 套用推荐场景 → 提交任务。
 *
 * 运行：node scripts/e2e-case-background-presets.mjs
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

/** 按可见文本找按钮并点击（真实鼠标事件） */
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
  return true;
}

async function textOf(page, selector) {
  return page.$eval(selector, (el) => el.value ?? el.textContent ?? '').catch(() => null);
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

  try {
    // 1. 打开任务页
    // 从根路径进入开发入口，再用侧边栏做客户端路由跳转。
    // 直接 GET /tasks 会被 vite 的 SPA fallback 交给 dist/index.html（生产产物），
    // 那样拿到的不是当前源码，测试就失去意义。
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(
      () => [...document.querySelectorAll('a')].some((a) => a.innerText.includes('任务列表')),
      { timeout: 20000 },
    );
    record('打开应用根路径', true, page.url());

    await page.evaluate(() => {
      const link = [...document.querySelectorAll('a')].find((a) => a.innerText.includes('任务列表'));
      link.click();
    });
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('创建任务')),
      { timeout: 20000 },
    );
    record('客户端路由跳转到任务页', page.url().includes('/tasks'), page.url());

    // 2. 打开创建任务弹窗
    await clickByText(page, '➕ 创建任务');
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('选择预设背景')),
      { timeout: 10000 },
    );
    const presetToggleLabel = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('选择预设背景'));
      return b.innerText.trim();
    });
    record('创建任务弹窗出现预设入口', /选择预设背景（28）/.test(presetToggleLabel), presetToggleLabel);
    await page.screenshot({ path: `${SHOT_DIR}/01-modal-open.png` });

    // 3. 展开预设面板
    await clickByText(page, '选择预设背景');
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '专项检材'),
      { timeout: 5000 },
    );
    const groupTabs = await page.evaluate(() =>
      [...document.querySelectorAll('button')]
        .map((b) => b.innerText.trim())
        .filter((t) => ['涉网犯罪', '入侵与恶意代码', '数据与知识产权', '人身与财产', '企业与合规', '专项检材'].includes(t)),
    );
    record('预设面板按 6 类分组展示', groupTabs.length === 6, groupTabs.join(' / '));
    await page.screenshot({ path: `${SHOT_DIR}/02-preset-panel.png` });

    // 4. 切到「入侵与恶意代码」分组
    await clickByText(page, '入侵与恶意代码', { exact: true });
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('勒索软件攻击')),
      { timeout: 5000 },
    );
    record('切换分组后显示对应预设', true, '勒索软件攻击 可见');

    // 5. 点击「勒索软件攻击」卡片
    const ransomwareText = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('勒索软件攻击'));
      return b.innerText;
    });
    record('预设卡片含名称与摘要', /勒索软件攻击/.test(ransomwareText) && /勒索信|加密|密钥/.test(ransomwareText), ransomwareText.replace(/\n/g, ' | '));

    await clickByText(page, '勒索软件攻击');
    const textareaValue = await textOf(page, 'textarea');
    const okFill = typeof textareaValue === 'string' && textareaValue.includes('勒索软件') && textareaValue.length > 150;
    record('点击预设后背景文本填入输入框', okFill, `长度 ${textareaValue?.length ?? 0}，开头「${(textareaValue || '').slice(0, 24)}…」`);

    // 6. 面板应自动收起
    const panelClosed = await page.evaluate(() =>
      ![...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '专项检材'),
    );
    record('选择后面板自动收起', panelClosed);

    // 7. 徽标显示为预设
    const badge = await page.evaluate(() => {
      const el = [...document.querySelectorAll('span')].find((s) => s.innerText.includes('勒索软件攻击') && s.innerText.includes('预设'));
      return el ? el.innerText.trim().replace(/\n/g, ' ') : null;
    });
    record('显示「预设」状态徽标', Boolean(badge), badge || '未找到');
    await page.screenshot({ path: `${SHOT_DIR}/03-preset-selected.png` });

    // 8. 推荐联动提示
    const recommendation = await page.evaluate(() => {
      const el = [...document.querySelectorAll('span, button')].find((s) => s.innerText.includes('建议筛选场景'));
      return el ? el.innerText.trim() : null;
    });
    record('展示推荐的筛选场景', Boolean(recommendation), recommendation || '未找到');

    // 9. 手动改动 → 回退自定义
    await page.click('textarea');
    await page.keyboard.press('End');
    await page.keyboard.type('补充：关注卷影副本删除记录。');
    await page.waitForFunction(
      () => [...document.querySelectorAll('span')].some((s) => s.innerText.includes('未使用预设，可手动输入')),
      { timeout: 5000 },
    );
    record('编辑后回退为自定义状态', true);

    // 10. 重新选回预设，套用推荐场景
    await clickByText(page, '选择预设背景');
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.includes('勒索软件攻击')),
      { timeout: 5000 },
    );
    await clickByText(page, '勒索软件攻击');
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '套用到分析场景'),
      { timeout: 5000 },
    );
    await clickByText(page, '套用到分析场景', { exact: true });
    const filterValue = await page.evaluate(() => {
      const sel = [...document.querySelectorAll('select')].find((s) =>
        [...s.options].some((o) => /病毒入侵|virus_intrusion/.test(o.textContent + o.value)));
      return sel ? { value: sel.value, text: sel.options[sel.selectedIndex]?.textContent?.trim() } : null;
    });
    record('套用推荐后过滤场景切换为病毒入侵', filterValue?.value === 'virus_intrusion',
      filterValue ? `${filterValue.value} (${filterValue.text})` : '未找到场景下拉框');
    await page.screenshot({ path: `${SHOT_DIR}/04-recommendation-applied.png` });

    // 11. 选择「电信网络诈骗」，验证跨分组 + 长文本
    await clickByText(page, '选择预设背景');
    await page.waitForFunction(
      () => [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '涉网犯罪'),
      { timeout: 5000 },
    );
    await clickByText(page, '涉网犯罪', { exact: true });
    await clickByText(page, '电信网络诈骗');
    const telecomValue = await textOf(page, 'textarea');
    record('切换分组后可选其他预设', telecomValue.includes('电信网络诈骗') && telecomValue.includes('受害人名单'),
      `长度 ${telecomValue.length}`);

    // 12. 检查 28 个预设全部可点（遍历全部分组）
    const allPresets = [];
    for (const group of ['涉网犯罪', '入侵与恶意代码', '数据与知识产权', '人身与财产', '企业与合规', '专项检材']) {
      // 面板可能已打开（按钮文案变成「收起预设」），仅在关闭时才点开。
      const panelOpen = await page.evaluate(() =>
        [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '专项检材'));
      if (!panelOpen) {
        await clickByText(page, '选择预设背景');
        await page.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => b.innerText.trim() === '专项检材'),
          { timeout: 5000 });
      }
      await clickByText(page, group, { exact: true });
      const cards = await page.evaluate(() => {
        const tabs = new Set(['涉网犯罪', '入侵与恶意代码', '数据与知识产权', '人身与财产', '企业与合规', '专项检材']);
        return [...document.querySelectorAll('button')]
          .filter((b) => b.getAttribute('aria-pressed') !== null && !tabs.has(b.innerText.trim()))
          .map((b) => b.innerText.split('\n')[0].trim());
      });
      allPresets.push(...cards);
    }
    record('28 个预设卡片全部渲染', allPresets.length === 28, `实际 ${allPresets.length}：${allPresets.join('、')}`);

    // 13. 提交任务，确认 case_description 原样到达后端
    // 使用仓库内真实存在的镜像，让请求通过后端路径校验，
    // 从而验证「预设文本 → HTTP 请求体 → 任务创建」整条链路。
    const IMAGE_PATH = process.env.E2E_IMAGE_PATH
      || '/home/ymj68520/projects/Forensics/TraceLens/test_image.img';

    // axios 在浏览器里走 XHR，不走 window.fetch，所以用 CDP 层监听请求体。
    const createRequests = [];
    page.on('request', (req) => {
      if (req.method() === 'POST' && /\/api\/tasks$/.test(new URL(req.url()).pathname)) {
        try { createRequests.push(JSON.parse(req.postData() || '{}')); } catch { /* ignore */ }
      }
    });

    // 填检材路径后提交
    await page.evaluate((imgPath) => {
      const input = [...document.querySelectorAll('input[type="text"]')].find((i) =>
        i.placeholder && i.placeholder.includes('/path/to/disk_image'));
      if (!input) throw new Error('找不到检材路径输入框');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, imgPath);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, IMAGE_PATH);
    await clickByText(page, '创建任务', { exact: true });
    await new Promise((r) => setTimeout(r, 5000));

    const createPayload = createRequests[0];
    if (createPayload) {
      record('提交载荷携带完整案情背景', createPayload.case_description === telecomValue,
        `case_description 长度 ${createPayload.case_description.length}，filter_profile=${createPayload.filter_profile}`);
      record('预设文本未被截断或改写', createPayload.case_description.length > 250,
        `前 30 字：${createPayload.case_description.slice(0, 30)}`);

      // 测试会在真实服务里建任务，跑完立即删除，避免污染任务列表。
      const cleanup = await page.evaluate(async () => {
        const res = await fetch('/api/tasks?limit=20');
        const data = await res.json();
        const tasks = (data.tasks || []).filter((t) =>
          t.status !== 'completed' && t.image_path && t.image_path.endsWith('test_image.img')
          && (t.case_description || '').startsWith('一起电信网络诈骗案件'));
        const deleted = [];
        for (const t of tasks) {
          const r = await fetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
          if (r.ok) deleted.push(t.id.slice(0, 8));
        }
        return deleted;
      });
      record('清理测试任务', true, cleanup.length ? `已删除 ${cleanup.join(', ')}` : '无可清理任务');
    } else {
      const errText = await page.evaluate(() => {
        const el = [...document.querySelectorAll('div')].find((d) => d.className.includes('bg-red-50'));
        return el ? el.innerText.trim() : null;
      });
      record('提交载荷携带完整案情背景', false, `未捕获到创建请求；页面错误：${errText || '无'}`);
    }
    await page.screenshot({ path: `${SHOT_DIR}/05-after-submit.png` });

    // 14. 检查控制台错误
    // 后端 4xx 是业务校验的正常反馈（由页面展示），不算前端运行时错误。
    const realErrors = consoleErrors.filter((e) =>
      !/favicon|Download the React DevTools|ResizeObserver loop|status of 4\d\d/i.test(e));
    record('无 JavaScript 运行时错误', realErrors.length === 0, realErrors.slice(0, 3).join(' | ') || '无');
  } catch (err) {
    record('测试执行', false, err.message);
    await page.screenshot({ path: `${SHOT_DIR}/error.png` }).catch(() => {});
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
