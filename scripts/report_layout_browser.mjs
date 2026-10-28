// report_layout_browser.mjs
// 真实渲染页的布局验收：加载 web 前端（vite dev + 真实 /api 代理），
// 打开指定任务的叙事报告，然后对每一章做几何测量：
//   1) 组件位置是否漂移：章节卡片的序号徽标 / 标题 / 小结块是否在预期容器内，
//      且相邻章节之间没有意外的垂直重叠；
//   2) 文字是否重叠：逐个可见文本节点做矩形相交检测（排除祖先/后代关系），
//      并检查所有元素是否横向溢出视口；
//   3) 证据召回表：表头与行是否横向溢出容器、单元格是否互相压字。
// 只做只读检查，不写任何后端状态。
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
// Tailwind resolves its `content` globs and the postcss config relative to the
// process cwd, not to Vite's root. Running from the repo root produced a page
// with no utility CSS at all (every element full-width), which then read as
// hundreds of "overlaps" — a measurement artifact, not a layout bug.
process.chdir(webRoot);
const output = await fs.mkdtemp(path.join(os.tmpdir(), 'tracelens-layout-'));
const taskId = process.env.REPORT_LAYOUT_TASK_ID;
const reportId = process.env.REPORT_LAYOUT_REPORT_ID || '';
const browserPath = process.env.CHROME_BIN || undefined;
const widths = (process.env.REPORT_LAYOUT_WIDTHS || '1440,1024,768,390')
  .split(',').map(value => Number(value.trim())).filter(Boolean);
if (!taskId) throw new Error('REPORT_LAYOUT_TASK_ID is required');

const server = await createServer({
  root: webRoot, configFile: path.join(webRoot, 'vite.config.js'), logLevel: 'warn',
  server: { host: '127.0.0.1', port: 0, hmr: false },
});
await server.listen();
const origin = `http://127.0.0.1:${server.httpServer.address().port}`;

const browser = await puppeteer.launch({
  executablePath: browserPath, headless: true,
  protocolTimeout: 180000,
  // Root in a container cannot use the sandbox; this is a local read-only
  // render of our own app, not an untrusted page.
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-background-networking',
    '--disable-component-update', '--disable-sync', '--no-first-run'],
});

// In-page geometry audit. Runs once per viewport.
const audit = () => {
  const visible = el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
      && style.display !== 'none' && Number(style.opacity) > 0.05;
  };
  const describe = el => {
    const rect = el.getBoundingClientRect();
    return {
      tag: el.tagName,
      testid: el.getAttribute?.('data-testid') || null,
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
      x: Math.round(rect.left), y: Math.round(rect.top),
      w: Math.round(rect.width), h: Math.round(rect.height),
    };
  };

  // (1) Text overlap inside the REPORT BODY only. The 911-row classification
  // panel has its own scroll box and is not part of the report's layout; a
  // whole-page O(n²) hit test on it both times out and measures nothing useful.
  const scope = document.querySelector('[data-testid="narrative-report-view"]') || document.body;
  const textNodes = [...scope.querySelectorAll('h1,h2,h3,h4,h5,p,li,td,th,span,button,a,strong,em,summary')]
    .filter(el => visible(el) && (el.textContent || '').trim().length > 0)
    .filter(el => ![...el.children].some(child => (child.textContent || '').trim().length > 0))
    .filter(el => !el.closest('[data-testid="report-classifications"]'))
    .filter(el => !el.closest('[data-testid="stage-analysis"]'));
  const clippedBy = el => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const style = getComputedStyle(p);
      if (/(auto|scroll|hidden|clip)/.test(style.overflowY + style.overflowX)) return p;
    }
    return null;
  };
  const reallyOnTop = (a, b, x, y) => {
    const hit = document.elementFromPoint(x, y);
    if (!hit) return false;
    return hit === a || hit === b || a.contains(hit) || b.contains(hit);
  };
  // Bucket by vertical band so only plausible neighbours are compared; the
  // report is a long vertical document and collisions are always local.
  const bands = new Map();
  const BAND = 240;
  textNodes.forEach(el => {
    const rect = el.getBoundingClientRect();
    const first = Math.floor(rect.top / BAND);
    const last = Math.floor(rect.bottom / BAND);
    for (let band = first; band <= last && band - first < 20; band += 1) {
      if (!bands.has(band)) bands.set(band, []);
      bands.get(band).push(el);
    }
  });
  const overlaps = [];
  const seenPairs = new Set();
  for (const bucket of bands.values()) {
    for (let i = 0; i < bucket.length; i += 1) {
      for (let j = i + 1; j < bucket.length; j += 1) {
        const a = bucket[i]; const b = bucket[j];
        if (a.contains(b) || b.contains(a)) continue;
        const ra = a.getBoundingClientRect(); const rb = b.getBoundingClientRect();
        const overlapX = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
        const overlapY = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        // 2px tolerance for sub-pixel rounding on inline elements sharing a line.
        if (overlapX <= 2 || overlapY <= 2) continue;
        const pairKey = a.textContent + '|' + b.textContent + '|' + Math.round(ra.top);
        if (seenPairs.has(pairKey)) continue;
        seenPairs.add(pairKey);
        // Two elements clipped by different containers cannot visually collide:
        // the scroll box hides one of them.
        if (clippedBy(a) !== clippedBy(b)) continue;
        const centerX = Math.max(ra.left, rb.left) + overlapX / 2;
        const centerY = Math.max(ra.top, rb.top) + overlapY / 2;
        if (centerX < 0 || centerY < 0 || centerX > window.innerWidth || centerY > window.innerHeight) continue;
        if (!reallyOnTop(a, b, centerX, centerY)) continue;
        overlaps.push({ a: describe(a), b: describe(b), overlapX: Math.round(overlapX), overlapY: Math.round(overlapY) });
        if (overlaps.length > 25) break;
      }
      if (overlaps.length > 25) break;
    }
    if (overlaps.length > 25) break;
  }

  // (2) Horizontal overflow: anything wider than the viewport, and anything
  // whose content escapes its own box (excluding intentional scroll containers
  // such as the recall table wrapper).
  const scrollContainers = new Set([...document.querySelectorAll('.overflow-x-auto,.overflow-y-auto,.overflow-auto')]);
  const isInScroller = el => { for (let p = el; p; p = p.parentElement) if (scrollContainers.has(p)) return true; return false; };
  const overflow = [...document.querySelectorAll('body *')].filter(el => {
    if (!visible(el) || isInScroller(el)) return false;
    // A nav drawer parked off-screen to the LEFT is the responsive pattern,
    // not a layout defect; only content that escapes the RIGHT edge (or is
    // clipped on both sides) pushes the page wider than the viewport.
    const rect = el.getBoundingClientRect();
    if (rect.left < -1 && rect.right <= 1) return false;
    return rect.right > window.innerWidth + 1;
  }).slice(0, 15).map(describe);

  // (3) Section geometry: every chapter card must be a vertical stack with no
  // interleaving; the summary block must sit inside its own card and below the
  // body text; the recall table must sit inside the first card.
  const cards = [...document.querySelectorAll('[data-testid="narrative-section"]')];
  const sectionRects = cards.map((card, index) => {
    const rect = card.getBoundingClientRect();
    const summary = card.querySelector('[data-testid="chapter-summary"]');
    const table = card.querySelector('[data-testid="evidence-recall-table"]');
    const body = card.querySelector('p.whitespace-pre-wrap');
    const header = card.querySelector('h3');
    return {
      index,
      testid: 'narrative-section',
      heading: (card.querySelector('h3')?.textContent || '').trim().slice(0, 40),
      top: Math.round(rect.top + window.scrollY), bottom: Math.round(rect.bottom + window.scrollY),
      width: Math.round(rect.width),
      headerInside: header ? rect.top <= header.getBoundingClientRect().top && header.getBoundingClientRect().bottom <= rect.bottom : null,
      bodyInside: body ? rect.top <= body.getBoundingClientRect().top && body.getBoundingClientRect().bottom <= rect.bottom + 1 : null,
      summaryInside: summary ? rect.top <= summary.getBoundingClientRect().top && summary.getBoundingClientRect().bottom <= rect.bottom + 1 : null,
      summaryBelowBody: (summary && body)
        ? summary.getBoundingClientRect().top >= body.getBoundingClientRect().bottom - 1 : null,
      tableInside: table ? rect.top <= table.getBoundingClientRect().top && table.getBoundingClientRect().bottom <= rect.bottom + 1 : null,
      tableBeforeSummary: (table && summary)
        ? table.getBoundingClientRect().bottom <= summary.getBoundingClientRect().top + 1 : null,
      hasSummary: Boolean(summary),
      hasTable: Boolean(table),
    };
  });
  const interleaved = [];
  for (let i = 1; i < sectionRects.length; i += 1) {
    if (sectionRects[i].top < sectionRects[i - 1].bottom - 1) interleaved.push([i - 1, i]);
  }

  // (4) Recall table internals: header and cells must not overlap each other.
  const table = document.querySelector('[data-testid="evidence-recall-table"]');
  let tableAudit = null;
  if (table) {
    const cells = [...table.querySelectorAll('th,td')].filter(visible);
    const cellOverlap = [];
    for (let i = 0; i < cells.length; i += 1) {
      for (let j = i + 1; j < cells.length; j += 1) {
        const ra = cells[i].getBoundingClientRect(); const rb = cells[j].getBoundingClientRect();
        if (Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left) > 2
          && Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 2) {
          cellOverlap.push({ a: describe(cells[i]), b: describe(cells[j]) });
        }
      }
    }
    const wrapper = table.querySelector('.overflow-x-auto');
    tableAudit = {
      rows: table.querySelectorAll('[data-testid="recall-row"]').length,
      headers: [...table.querySelectorAll('thead th')].map(th => th.textContent.trim()),
      cellsOverlapping: cellOverlap.slice(0, 10),
      wrapperScrolls: wrapper ? wrapper.scrollWidth > wrapper.clientWidth + 1 : null,
      tableWidth: Math.round(table.getBoundingClientRect().width),
      viewport: window.innerWidth,
    };
  }

  return {
    viewport: { width: window.innerWidth, height: window.innerHeight },
    documentWidth: document.documentElement.scrollWidth,
    content: {
      sections: cards.length,
      summaries: document.querySelectorAll('[data-testid="chapter-summary"]').length,
      recallTables: document.querySelectorAll('[data-testid="evidence-recall-table"]').length,
      recallRows: document.querySelectorAll('[data-testid="recall-row"]').length,
      // Prompt-internal ids (m0012) must never reach a reader; the advisory
      // checklist and the difference chapter used to publish them verbatim.
      materialIdLeaks: (() => {
        const view = document.querySelector('[data-testid="narrative-sections"]');
        if (!view) return [];
        const hits = [];
        for (const section of view.querySelectorAll('[data-testid="narrative-section"]')) {
          const text = section.textContent || '';
          const match = /(?<![A-Za-z0-9_])m\d{3,4}(?![A-Za-z0-9_])/.exec(text);
          if (match) hits.push({ heading: (section.querySelector('h3')?.textContent || '').trim(), match: match[0] });
        }
        return hits;
      })(),
      firstHeading: document.querySelector('[data-testid="narrative-section"] h3')?.textContent?.trim() || null,
    },
    overlaps, overflow, interleaved, sections: sectionRects, table: tableAudit,
  };
};

const results = { mode: 'REAL_BACKEND_RENDER', task_id: taskId, report_id: reportId || '(latest)',
  browser: await browser.version(), started_at: new Date().toISOString(), viewports: [], output };
let failure = null;
try {
  for (const width of widths) {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.setViewport({ width, height: 1000 });
    const url = `${origin}/case-intelligence?task_id=${encodeURIComponent(taskId)}`
      + `&tab=forensic${reportId ? `&report_id=${encodeURIComponent(reportId)}` : ''}`;
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
    await page.waitForSelector('[data-testid="narrative-sections"]', { timeout: 90000 });
    // Let fonts/layout settle and force the summary/table into view.
    await page.evaluate(() => document.fonts?.ready);
    await new Promise(resolve => setTimeout(resolve, 400));
    const report = await page.evaluate(audit);
    report.pageErrors = pageErrors;
    report.url = url;
    // A full-page capture of a 14-chapter report exceeds Chrome's texture
    // limit ("Page is too large"), so the evidence screenshots are per
    // chapter plus one of the first chapter's table. The assertions above
    // already cover the geometry; the images are for human review.
    const shots = [];
    const cards = await page.$$('[data-testid="narrative-section"]');
    for (const [index, card] of cards.entries()) {
      const file = path.join(output, `section-${width}-${String(index + 1).padStart(2, '0')}.png`);
      try {
        await card.screenshot({ path: file });
        shots.push(file);
      } catch {
        // A chapter taller than the capture limit is fine: the geometry
        // checks already ran against its real rects.
      }
    }
    const table = await page.$('[data-testid="evidence-recall-table"]');
    if (table) {
      const file = path.join(output, `recall-table-${width}.png`);
      try { await table.screenshot({ path: file }); shots.push(file); } catch { /* size limit */ }
    }
    report.screenshots = shots;
    results.viewports.push(report);

    // Assertions — geometry, not pixel snapshots.
    assert.equal(report.pageErrors.length, 0, `page errors: ${report.pageErrors.join('; ')}`);
    assert.ok(report.content.sections > 0, 'no chapters rendered');
    assert.equal(report.overlaps.length, 0, `text overlap: ${JSON.stringify(report.overlaps.slice(0, 3))}`);
    assert.equal(report.overflow.length, 0, `horizontal overflow: ${JSON.stringify(report.overflow.slice(0, 3))}`);
    assert.equal(report.interleaved.length, 0, `chapters interleaved: ${JSON.stringify(report.interleaved)}`);
    assert.equal(report.content.materialIdLeaks.length, 0,
      `prompt-internal material ids in published prose: ${JSON.stringify(report.content.materialIdLeaks)}`);
    assert.ok(report.documentWidth <= width + 1, `document wider than viewport: ${report.documentWidth} > ${width}`);
    for (const section of report.sections) {
      if (section.headerInside === false) throw new Error(`heading escapes chapter ${section.index}: ${section.heading}`);
      if (section.bodyInside === false) throw new Error(`body escapes chapter ${section.index}: ${section.heading}`);
      if (section.summaryInside === false) throw new Error(`summary escapes chapter ${section.index}: ${section.heading}`);
      if (section.summaryBelowBody === false) throw new Error(`summary overlaps body in chapter ${section.index}: ${section.heading}`);
      if (section.tableInside === false) throw new Error(`recall table escapes chapter ${section.index}`);
      if (section.tableBeforeSummary === false) throw new Error(`summary rendered before the recall table in chapter ${section.index}`);
    }
    if (report.content.summaries !== report.content.sections) {
      throw new Error(`summary count ${report.content.summaries} != chapter count ${report.content.sections}`);
    }
    if (report.table) {
      assert.equal(report.table.cellsOverlapping.length, 0,
        `recall table cells overlap: ${JSON.stringify(report.table.cellsOverlapping.slice(0, 3))}`);
      assert.ok(report.table.rows > 0, 'recall table rendered no rows');
      assert.equal(report.content.recallTables, 1, 'exactly one recall table expected');
    }
    await page.close();
    console.log(`PASS ${width}px sections=${report.content.sections} summaries=${report.content.summaries} rows=${report.table?.rows ?? 0}`);
  }
  results.status = 'PASS';
} catch (error) {
  failure = error;
  results.status = 'FAIL';
  results.error = error.stack;
  console.error(`FAIL ${error.message}`);
} finally {
  await fs.writeFile(path.join(output, 'layout-report.json'), JSON.stringify(results, null, 2));
  await browser.close();
  await server.close();
}
console.log(`artifacts: ${output}`);
if (failure) process.exitCode = 1;
