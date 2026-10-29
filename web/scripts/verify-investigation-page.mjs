#!/usr/bin/env node
/**
 * Full-page acceptance for the file-centric investigation workbench.
 *
 * For each finished task, on the real page:
 *   1. left column  — "文件关联调查事件" header counts the linked events and
 *                     lists them (title / time / AI 草稿 badge);
 *   2. click path A — left event row -> right column switches to the event
 *                     panel (返回文件工作台 / 事件总结 / 证据构成);
 *   3. back to file workbench;
 *   4. click path B — middle timeline node expands its file card, the
 *                     佐证事件 block renders, its event link switches the
 *                     right column to the event panel too.
 *
 * Usage: node scripts/verify-investigation-page.mjs
 */
import { chromium } from '/root/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.mjs';
import { mkdirSync } from 'node:fs';

const BASE = process.env.BASE || 'http://127.0.0.1:8666';
const OUT = process.env.OUT || '/tmp/shots/final';
mkdirSync(OUT, { recursive: true });

const TASKS = [
  { id: '5c492d22-1427-4be7-8f37-f455ff3d6832', label: 'windows-5c492d22' },
  { id: 'e9704679-710e-4d35-ba97-bfdf76795ce9', label: 'linux-e9704679' },
];

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await (await browser.newContext({ viewport: { width: 1680, height: 1100 } })).newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
page.on('pageerror', (e) => errors.push('pageerror: ' + String(e).slice(0, 200)));

const report = {};

for (const task of TASKS) {
  const r = { url: `${BASE}/investigation?task_id=${task.id}` };
  await page.goto(r.url, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForSelector('[data-testid="file-event-panel"]', { timeout: 90000 });
  await page.waitForSelector('[data-testid^="file-event-ie_"]', { timeout: 90000 });
  await page.waitForTimeout(2500);

  // 1. left column -----------------------------------------------------------------
  const left = page.locator('[data-testid="file-event-panel"]');
  const leftText = (await left.innerText()).replace(/\s+/g, ' ');
  r.left = {
    header: leftText.match(/文件关联调查事件 \d+/)?.[0] || null,
    eventRows: await page.locator('[data-testid^="file-event-ie_"]').count(),
    firstRow: (await page.locator('[data-testid^="file-event-ie_"]').first().innerText())
      .replace(/\s+/g, ' ').trim(),
    macbChips: /创建 .*修改 /.test(leftText),
  };
  await page.screenshot({ path: `${OUT}/${task.label}-1-left.png` });

  // 2. left event row -> right event panel ------------------------------------------
  await page.locator('[data-testid^="file-event-ie_"]').first().click();
  await page.waitForTimeout(5000);
  const paneText = (await page.locator('[data-testid="analysis-workspace-column"]').innerText())
    .replace(/\s+/g, ' ');
  r.eventPane = {
    hasBackLink: paneText.includes('返回文件工作台'),
    hasSummary: paneText.includes('事件总结'),
    hasEvidenceMix: paneText.includes('证据构成'),
    excerpt: paneText.slice(0, 300),
  };
  await page.screenshot({ path: `${OUT}/${task.label}-2-event-pane.png` });

  // 3. back to file workbench ---------------------------------------------------------
  await page.getByText('返回文件工作台').click();
  await page.waitForTimeout(2500);
  const backText = (await page.locator('[data-testid="analysis-workspace-column"]').innerText())
    .replace(/\s+/g, ' ');
  r.backToFile = { showsFileEvidence: backText.includes('FILE EVIDENCE') };

  // 4. middle timeline -> 佐证事件 -> event panel ---------------------------------------
  const tl = page.locator('[data-testid="investigation-timeline"]');
  await tl.evaluate((el) => { el.scrollTop = 0; });
  await page.waitForTimeout(1000);
  const node = page.locator('button[data-testid^="file-node-"]').first();
  await node.scrollIntoViewIfNeeded();
  await node.click();
  await page.waitForTimeout(2500);
  const cards = page.locator('[data-testid^="file-card-"]');
  const cardText = (await cards.count())
    ? (await cards.first().innerText()).replace(/\s+/g, ' ') : '';
  r.timeline = {
    fileCardExpanded: (await cards.count()) > 0,
    corroboratingCount: Number(cardText.match(/佐证事件 · (\d+)/)?.[1] ?? -1),
  };
  const link = page.locator('[data-testid^="file-card-event-"]').first();
  if (await link.count()) {
    await link.click();
    await page.waitForTimeout(4500);
    const pane2 = (await page.locator('[data-testid="analysis-workspace-column"]').innerText())
      .replace(/\s+/g, ' ');
    r.timeline.timelineEventOpensPane = pane2.includes('返回文件工作台') && pane2.includes('事件总结');
  } else {
    r.timeline.timelineEventOpensPane = null;
  }
  await page.screenshot({ path: `${OUT}/${task.label}-3-timeline-corroborating.png` });

  report[task.label] = r;
}

report.consoleErrors = errors.slice(0, 8);
console.log(JSON.stringify(report, null, 2));
await browser.close();
