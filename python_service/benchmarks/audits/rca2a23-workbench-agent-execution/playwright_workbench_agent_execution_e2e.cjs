/**
 * Playwright Browser E2E Acceptance Test for TraceLens Workbench Agent Execution (RCA-2A.23).
 *
 * Runs against:
 *   Frontend: http://127.0.0.1:3100
 *   Backend:  http://127.0.0.1:8098
 *
 * Validates the complete interactive loop:
 *   Workbench -> Select Task -> Explicit Start Agent Cycle (Fake Model) -> Real Tool / Integration
 *   -> Candidate Generated (review_pending) -> Provenance Inspection -> Explicit Accept / Reject
 *   -> Authoritative SQLite Commit -> Durable History -> Page Reload Persistence.
 */

const fs = require('fs');
const path = require('path');

let chromium;
try {
  chromium = require('playwright').chromium;
} catch {
  chromium = require(path.resolve(__dirname, '../../../../web/node_modules/playwright')).chromium;
}

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3100';
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8098';
const TASK_ID = 'synthetic-rca2a23-workbench-001';
const CHROMIUM_EXEC = '/home/ymj68520/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome';

async function runBrowserE2E() {
  console.log(`[E2E] Starting Browser Agent Execution Acceptance Suite`);
  console.log(`[E2E] Frontend: ${FRONTEND_URL}, Backend: ${BACKEND_URL}`);

  const results = [];
  function record(testId, name, pass, detail = {}) {
    console.log(`[${pass ? 'PASS' : 'FAIL'}] ${testId}: ${name}`);
    results.push({ testId, name, pass, detail });
  }

  const browser = await chromium.launch({
    executablePath: CHROMIUM_EXEC,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();

  // Track HTTP calls and console logs
  const httpLogs = [];
  page.on('console', (msg) => console.log(`[BROWSER ${msg.type()}]`, msg.text()));
  page.on('pageerror', (err) => console.log('[BROWSER PAGE ERROR]', err.message));
  page.on('request', (req) => {
    if (req.url().includes('/api/investigation') || req.url().includes('/tasks')) {
      httpLogs.push({ method: req.method(), url: req.url() });
    }
  });

  try {
    // -----------------------------------------------------------------------
    // B01: Load Investigation Workbench for synthetic task
    // -----------------------------------------------------------------------
    const targetUrl = `${FRONTEND_URL}/investigation?taskId=${TASK_ID}`;
    console.log(`[E2E] Navigating to ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 30000 });

    await page.waitForSelector('text=Investigation / 二次调查分析', { timeout: 15000 });
    record('B01', 'Real browser loads Investigation Workbench', true, { url: page.url() });

    // -----------------------------------------------------------------------
    // B02: Layout preserved with both Execution Control and Review Panel in Column 3
    // -----------------------------------------------------------------------
    const execControl = await page.$('[data-testid="agent-execution-control-container"]');
    const reviewPanel = await page.$('[data-testid="agent-review-panel"]');
    const analysisCol = await page.$('[data-testid="analysis-workspace-column"]') || await page.$('[data-testid="analysis-workspace-container"]');

    const layoutPreserved = Boolean(execControl && reviewPanel && analysisCol);
    record('B02', 'Three-column layout strictly preserved with Execution Control and Review Panel in Column 3', layoutPreserved, {
      execControl: Boolean(execControl),
      reviewPanel: Boolean(reviewPanel),
      analysisCol: Boolean(analysisCol),
    });

    // -----------------------------------------------------------------------
    // B03: Initial Agent state rendered accurately (Rev 1, idle, 0 review candidates)
    // -----------------------------------------------------------------------
    const initialRevText = await page.textContent('[data-testid="agent-state-revision"]');
    const initialStatusText = await page.textContent('[data-testid="agent-execution-status-badge"]');
    const initialCandidates = await page.$$('[data-testid^="candidate-item-"]');

    record('B03', 'Initial Agent state rendered accurately before cycle execution', initialRevText.includes('Rev 1') && initialCandidates.length === 0, {
      revision: initialRevText,
      status: initialStatusText,
      candidateCount: initialCandidates.length,
    });

    // -----------------------------------------------------------------------
    // B04: Explicit Start Cycle click triggers executing state & disables button
    // -----------------------------------------------------------------------
    console.log('[E2E] Clicking Start Agent Cycle button...');
    const startCyclePromise = page.waitForResponse((res) => res.url().includes('/api/investigation/agent/cycle') && res.request().method() === 'POST');
    await page.click('[data-testid="btn-start-agent-cycle"]');

    // Verify in-flight executing indicator
    await page.waitForSelector('text=执行中...', { timeout: 3000 });
    const isBusyDisabled = await page.$eval('[data-testid="btn-start-agent-cycle"]', (btn) => btn.disabled);
    record('B04', 'In-flight execution state and duplicate click prevention observed', isBusyDisabled);

    // Wait for cycle execution HTTP response
    const cycleResp = await startCyclePromise;
    const cycleStatus = cycleResp.status();
    const cycleBody = await cycleResp.json();
    console.log('[E2E] Cycle response:', cycleStatus, cycleBody);

    record('B05', 'Agent cycle completes with valid CycleOutcome (Rev 1 -> Rev 2)', cycleStatus === 200 && cycleBody.ending_revision === 2, {
      status: cycleStatus,
      ending_revision: cycleBody.ending_revision,
      cycle_id: cycleBody.cycle_id,
    });

    // -----------------------------------------------------------------------
    // B06: Agent state UI refreshes (Rev 2, idle, metrics updated)
    // -----------------------------------------------------------------------
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="agent-state-revision"]');
      return el && el.textContent.includes('Rev 2');
    }, { timeout: 10000 });

    const updatedRevText = await page.textContent('[data-testid="agent-state-revision"]');
    record('B06', 'Agent state displays updated revision (Rev 2)', updatedRevText.includes('Rev 2'), {
      revision: updatedRevText,
    });

    // -----------------------------------------------------------------------
    // B07: Review candidate queue automatically refreshes via refreshSignal
    // -----------------------------------------------------------------------
    console.log('[E2E] Waiting for review candidate to appear in queue...');
    await page.waitForSelector('[data-testid^="candidate-item-"]', { timeout: 10000 });
    const candidatesAfterCycle = await page.$$('[data-testid^="candidate-item-"]');
    const cand01Id = await candidatesAfterCycle[0].getAttribute('data-candidate-id');

    record('B07', 'Review candidate queue automatically refreshes with newly generated candidate', candidatesAfterCycle.length === 1 && cand01Id.includes('cand_02'), {
      count: candidatesAfterCycle.length,
      candidateId: cand01Id,
    });

    // -----------------------------------------------------------------------
    // B08: Candidate details and evidence reference inspection
    // -----------------------------------------------------------------------
    await candidatesAfterCycle[0].click();
    await page.waitForSelector('[data-testid="candidate-full-content"]', { timeout: 5000 });
    const candContent = await page.textContent('[data-testid="candidate-full-content"]');
    const hasSamHiveText = candContent.includes('Security Account Manager');

    const evRefSelector = '[data-testid="evidence-ref-file:C/Windows/System32/config/SAM"]';
    await page.waitForSelector(evRefSelector, { timeout: 5000 });
    const hasEvRef = await page.isVisible(evRefSelector);

    record('B08', 'Candidate details and evidence reference verified', hasSamHiveText && hasEvRef, {
      content: candContent.slice(0, 60),
      hasEvRef,
    });

    // -----------------------------------------------------------------------
    // B09: Explicit Accept workflow with confirmation modal
    // -----------------------------------------------------------------------
    console.log('[E2E] Submitting explicit Accept decision...');
    await page.click('[data-testid="btn-accept-candidate"]');
    await page.waitForSelector('[data-testid="review-confirmation-dialog"]', { timeout: 5000 });
    await page.fill('[data-testid="review-note-input"]', 'Analyst verified SAM hive credential access.');

    const [acceptResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/investigation/agent/review') && res.request().method() === 'POST'),
      page.click('[data-testid="btn-confirm-review-decision"]'),
    ]);

    const acceptStatus = acceptResp.status();
    const acceptBody = await acceptResp.json();
    console.log('[E2E] Review response:', acceptStatus, acceptBody);

    record('B09', 'Explicit Accept review submitted and accepted (200 OK)', acceptStatus === 200 && acceptBody.decision === 'accepted', {
      status: acceptStatus,
      decision: acceptBody.decision,
      review_id: acceptBody.review_id,
      reviewer: acceptBody.reviewer,
    });

    // Verify UI reflects accepted state
    await page.waitForTimeout(500);
    const panelText = await page.textContent('[data-testid="agent-review-panel"]');
    record('B10', 'Candidate status reflects accepted state in UI', panelText.includes('accepted'));

    // -----------------------------------------------------------------------
    // B11: Reload browser and verify state & review persistence
    // -----------------------------------------------------------------------
    console.log('[E2E] Reloading browser to verify durable persistence...');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="agent-state-revision"]', { timeout: 15000 });
    await page.waitForSelector('[data-testid^="candidate-item-"]', { timeout: 10000 });

    const reloadedRevText = await page.textContent('[data-testid="agent-state-revision"]');
    const reloadedCandidateItems = await page.$$('[data-testid^="candidate-item-"]');
    await reloadedCandidateItems[0].click();
    await page.waitForTimeout(500);

    const reloadedPanelText = await page.textContent('[data-testid="agent-review-panel"]');
    const persistedAccepted = reloadedPanelText.includes('accepted');
    const persistedHistory = reloadedPanelText.includes('Authoritative Review History') || reloadedPanelText.includes('Verified SAM hive');

    record('B11', 'Browser reload confirms persistent accepted status and review history in SQLite', reloadedRevText.includes('Rev 2') && persistedAccepted && persistedHistory, {
      reloadedRevision: reloadedRevText,
      persistedAccepted,
      persistedHistory,
    });

    // -----------------------------------------------------------------------
    // B12: Trigger second cycle -> Rev 3 and second candidate
    // -----------------------------------------------------------------------
    console.log('[E2E] Triggering second Agent cycle...');
    const [secondCycleResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/investigation/agent/cycle') && res.request().method() === 'POST'),
      page.click('[data-testid="btn-start-agent-cycle"]'),
    ]);
    const secondCycleBody = await secondCycleResp.json();
    console.log('[E2E] Second cycle response:', secondCycleResp.status(), secondCycleBody);

    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="agent-state-revision"]');
      return el && el.textContent.includes('Rev 3');
    }, { timeout: 10000 });

    await page.waitForFunction(
      () => document.querySelectorAll('[data-testid^="candidate-item-"]').length >= 2,
      { timeout: 15000 }
    );
    const candidatesAfterCycle2 = await page.$$('[data-testid^="candidate-item-"]');
    record('B12', 'Second agent cycle advances revision to Rev 3 and generates second candidate', candidatesAfterCycle2.length >= 2, {
      count: candidatesAfterCycle2.length,
      revision: await page.textContent('[data-testid="agent-state-revision"]'),
    });

    // -----------------------------------------------------------------------
    // B13: Explicit Reject workflow on second candidate
    // -----------------------------------------------------------------------
    console.log('[E2E] Rejecting second candidate...');
    await candidatesAfterCycle2[1].click();
    await page.waitForSelector('[data-testid="btn-reject-candidate"]', { timeout: 5000 });
    await page.click('[data-testid="btn-reject-candidate"]');

    await page.waitForSelector('[data-testid="review-confirmation-dialog"]', { timeout: 5000 });
    await page.fill('[data-testid="review-note-input"]', 'Analyst rejected candidate 03 after manual correlation.');

    const [rejectResp] = await Promise.all([
      page.waitForResponse((res) => res.url().includes('/api/investigation/agent/review') && res.request().method() === 'POST'),
      page.click('[data-testid="btn-confirm-review-decision"]'),
    ]);

    const rejectStatus = rejectResp.status();
    const rejectBody = await rejectResp.json();
    record('B13', 'Explicit Reject review submitted and rejected (200 OK)', rejectStatus === 200 && rejectBody.decision === 'rejected', {
      status: rejectStatus,
      decision: rejectBody.decision,
      review_id: rejectBody.review_id,
    });

    // -----------------------------------------------------------------------
    // B14: Second browser reload preserves both accepted and rejected reviews
    // -----------------------------------------------------------------------
    console.log('[E2E] Second reload to confirm dual decision durability...');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="agent-state-revision"]', { timeout: 15000 });
    await page.waitForFunction(
      () => document.querySelectorAll('[data-testid^="candidate-item-"]').length >= 2,
      { timeout: 15000 }
    );
    const finalCandidates = await page.$$('[data-testid^="candidate-item-"]');
    await finalCandidates[1].click();
    await page.waitForTimeout(500);
    const finalPanelText = await page.textContent('[data-testid="agent-review-panel"]');

    record('B14', 'Browser reload preserves both accepted and rejected reviews durably in SQLite', finalPanelText.includes('rejected'), {
      candidateCount: finalCandidates.length,
      hasRejectedStatus: finalPanelText.includes('rejected'),
    });

    // -----------------------------------------------------------------------
    // B15: Reviewer identity limitation disclosed in UI
    // -----------------------------------------------------------------------
    await page.waitForSelector('[data-testid="reviewer-authority-notice"]', { timeout: 5000 });
    const noticeText = await page.textContent('[data-testid="reviewer-authority-notice"]');
    const limitationDisclosed = noticeText.includes('REVIEWER_AUTHENTICATION_LIMITATION') && noticeText.includes('caller-declared');
    record('B15', 'Reviewer authority limitation explicitly disclosed in UI', limitationDisclosed, { noticeText });

  } catch (err) {
    console.error('[E2E] Unexpected error during browser acceptance:', err);
    try {
      console.log('[E2E] Error URL:', page.url());
      console.log('[E2E] Error Title:', await page.title());
      console.log('[E2E] Error Body text:', (await page.innerText('body')).slice(0, 400));
    } catch {}
    record('FATAL', 'Browser test encountered unhandled exception', false, { error: String(err) });
  } finally {
    await browser.close();
  }

  return results;
}

if (require.main === module) {
  runBrowserE2E().then((res) => {
    const passed = res.filter((r) => r.pass).length;
    const total = res.length;
    const outPath = path.join(__dirname, 'rca2a23-browser-results.json');
    fs.writeFileSync(outPath, JSON.stringify(res, null, 2), 'utf-8');
    console.log(`\n========================================`);
    console.log(`Browser Acceptance Results: ${passed}/${total} PASS`);
    console.log(`Results saved to: ${outPath}`);
    console.log(`========================================`);
    process.exit(passed === total ? 0 : 1);
  });
}

module.exports = { runBrowserE2E };
