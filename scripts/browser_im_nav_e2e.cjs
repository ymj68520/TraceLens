#!/usr/bin/env node
/* 即时通讯取证页（/im-forensics）页内导航 无头浏览器 E2E。
 *
 * 验证范围（对应反馈"子页面切换后不能互相切换也不能回到即时通讯页面"）：
 *   1. 六个 Tab 常驻可见，微信 / QQ 两个平台一致；
 *   2. 任意 Tab 之间可互相切换（URL tab 参数 + 高亮 + 内容真实渲染）；
 *   3. 会话列表 → 聊天记录跳转后仍停留在页内；
 *   4. 浏览器返回可逐级回退且不脱离本页；
 *   5. 侧栏任意页进入 / 返回 即时通讯 页面正常；
 *   6. 深链与旧路由（/wechat-forensics、/qq-forensics、/wechat-graph）落地后 Tab 栏仍在。
 *
 * 前置：8666 端口服务在线；无头 Chromium 已以 --remote-debugging-port=9222 启动。
 * 运行：node scripts/browser_im_nav_e2e.cjs
 */
const { chromium } = require('../web/node_modules/playwright');

const BASE = process.env.IM_E2E_BASE || 'http://127.0.0.1:8666';
const TABS = ['取证概览', '会话列表', '聊天记录', '联系人', '群聊', '关系分析'];
const TAB_ID = {
  取证概览: 'overview', 会话列表: 'sessions', 聊天记录: 'messages',
  联系人: 'contacts', 群聊: 'chatrooms', 关系分析: 'graph',
};

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

async function activeTab(page) {
  return page.$$eval('button', (btns) => {
    const el = btns.find((b) => b.className.includes('bg-primary-600') && /取证概览|会话列表|聊天记录|联系人|群聊|关系分析/.test(b.textContent));
    return el ? el.textContent.trim() : null;
  });
}

async function tabBarVisible(page) {
  return page.evaluate((labels) => {
    const btns = [...document.querySelectorAll('button')].map((b) => b.textContent.trim());
    return labels.every((t) => btns.includes(t));
  }, TABS);
}

async function clickTab(page, label) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.waitForTimeout(1200);
}

async function mainContentHas(page, needle) {
  const text = await page.locator('main').innerText();
  return text.includes(needle);
}

(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0] || (await browser.newContext());
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1600, height: 900 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  try {
    // ---- 1. 微信平台：六个 Tab 依次正向切换 ----
    await page.goto(`${BASE}/im-forensics`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    check('进入 /im-forensics 自动选中导入', /import_id=.+/.test(page.url()), page.url());
    check('微信平台 Tab 栏完整可见', await tabBarVisible(page));

    for (const t of TABS) {
      await clickTab(page, t);
      const urlOk = page.url().includes(`tab=${TAB_ID[t]}`);
      const active = await activeTab(page);
      check(`正向切换到「${t}」`, urlOk && active === t, `url tab=${urlOk} 高亮=${active}`);
    }
    check('切换后 Tab 栏仍完整可见', await tabBarVisible(page));

    // 内容真实渲染（微信演示集）
    await clickTab(page, '取证概览');
    check('概览内容渲染（消息总数）', await mainContentHas(page, '消息总数'));
    await clickTab(page, '会话列表');
    check('会话列表内容渲染（表头）', await mainContentHas(page, '最后消息预览'));
    await clickTab(page, '聊天记录');
    check('聊天记录内容渲染（共 N 条）', /共 \d+ 条/.test(await page.locator('main').innerText()));
    await clickTab(page, '联系人');
    check('联系人内容渲染（显示 N 条）', await mainContentHas(page, '显示'));
    await clickTab(page, '群聊');
    check('群聊内容渲染', (await mainContentHas(page, '群主')) || (await mainContentHas(page, '@chatroom')));

    // ---- 2. 互相切换（逆序跳跃）----
    await clickTab(page, '会话列表');
    check('关系分析 → 会话列表（互切）', page.url().includes('tab=sessions') && (await activeTab(page)) === '会话列表');
    await clickTab(page, '聊天记录');
    check('会话列表 → 聊天记录（互切）', page.url().includes('tab=messages') && (await activeTab(page)) === '聊天记录');
    await clickTab(page, '取证概览');
    check('聊天记录 → 取证概览（互切）', page.url().includes('tab=overview') && (await activeTab(page)) === '取证概览');

    // ---- 3. 会话行 → 聊天记录（页内跳转不脱离本页）----
    await clickTab(page, '会话列表');
    const firstRow = page.locator('main table tbody tr').first();
    const rowText = await firstRow.innerText();
    await firstRow.click();
    await page.waitForTimeout(1200);
    check('点击会话行跳转聊天记录', page.url().includes('tab=messages') && (await activeTab(page)) === '聊天记录');
    check('跳转后 Tab 栏仍可见', await tabBarVisible(page));

    // ---- 4. 浏览器返回：逐级回退且不脱离 /im-forensics ----
    await page.goBack();
    await page.waitForTimeout(800);
    check('浏览器返回 #1 回到会话列表', page.url().includes('tab=sessions') && (await activeTab(page)) === '会话列表');
    await page.goBack();
    await page.waitForTimeout(800);
    const back2Tab = await activeTab(page);
    check('浏览器返回 #2 仍停留在即时通讯页', page.url().startsWith(`${BASE}/im-forensics`) && back2Tab !== null, `当前 Tab=${back2Tab}`);

    // ---- 5. 跨页进入 + 侧栏返回 ----
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
    await page.getByRole('link', { name: /IM Forensics|即时通讯/ }).click();
    await page.waitForTimeout(1800);
    check('从 Dashboard 侧栏进入即时通讯页', page.url().startsWith(`${BASE}/im-forensics`));
    await clickTab(page, '联系人');
    await page.getByRole('link', { name: /IM Forensics|即时通讯/ }).click();
    await page.waitForTimeout(1200);
    const sidebarReturnTab = await activeTab(page);
    check('子页面上点侧栏回到即时通讯页（概览）', page.url().startsWith(`${BASE}/im-forensics`) && sidebarReturnTab === '取证概览', `当前 Tab=${sidebarReturnTab}`);

    // ---- 6. QQ 平台：Tab 栏一致 + 互切 ----
    await page.goto(`${BASE}/im-forensics?platform=qq`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2200);
    check('QQ 平台 Tab 栏完整可见', await tabBarVisible(page));
    await clickTab(page, '群聊');
    check('QQ 切到群聊', page.url().includes('tab=chatrooms') && (await activeTab(page)) === '群聊');
    await clickTab(page, '会话列表');
    check('QQ 群聊 → 会话列表（互切）', page.url().includes('tab=sessions') && (await activeTab(page)) === '会话列表');
    check('QQ 会话内容渲染（表头）', await mainContentHas(page, '最后消息预览'));

    // ---- 7. 深链 + 旧路由落地 ----
    await page.goto(`${BASE}/im-forensics?tab=chatrooms`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1800);
    check('深链 ?tab=chatrooms 直接落地且 Tab 栏可见', page.url().includes('tab=chatrooms') && (await tabBarVisible(page)));

    for (const [from, expectPart] of [
      ['/wechat-forensics', 'platform=wechat'],
      ['/qq-forensics', 'platform=qq'],
      ['/wechat-graph', 'tab=graph'],
    ]) {
      await page.goto(`${BASE}${from}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1800);
      check(`旧路由 ${from} 重定向并保留 Tab 栏`, page.url().includes(expectPart) && (await tabBarVisible(page)), page.url());
    }

    check('全程无页面 JS 错误', errors.length === 0, errors.slice(0, 3).join(' | '));
  } finally {
    await page.close();
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 项通过`);
  if (failed.length) {
    console.log('失败项：', failed.map((f) => f.name).join('；'));
    process.exit(1);
  }
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
