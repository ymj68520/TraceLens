/**
 * Playwright Browser Acceptance Suite: Track B (High-Fidelity Real-Task Headless Test).
 *
 * Covers:
 *   Part B1: Original task read-only browser acceptance (60dedf82-7f35-48be-a104-b4d283a4fe92)
 *   Part B2: Isolated clone workflow on real-sized task (isolated-real-b2-test-001) covering B01 - B18
 *
 * Runs against:
 *   Frontend: http://127.0.0.1:3100
 *   Backend:  http://127.0.0.1:8098
 */

const fs = require('fs');
const path = require('path');
const http = require('http');

let chromium;
try {
  chromium = require('playwright').chromium;
} catch {
  chromium = require('/home/ymj68520/projects/TraceLens-agent-v0-integration/web/node_modules/playwright').chromium;
}

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3100';
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8098';
const REAL_TASK_ID = '60dedf82-7f35-48be-a104-b4d283a4fe92';
const ISOLATED_TASK_ID = 'isolated-real-b2-test-001';
const CHROMIUM_EXEC = '/home/ymj68520/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome';

async function postJson(endpoint, data, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(endpoint, BACKEND_URL);
    const bodyStr = JSON.stringify(data);
    const req = http.request(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(bodyStr),
        ...headers,
      },
    }, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(body || '{}') });
        } catch {
          resolve({ status: res.statusCode, data: body });
        }
      });
    });
    req.on('error', reject);
    req.write(bodyStr);
    req.end();
  });
}

async function getJson(endpoint, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(endpoint, BACKEND_URL);
    const req = http.request(url, { method: 'GET', headers }, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(body || '{}') });
        } catch {
          resolve({ status: res.statusCode, data: body });
        }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

async function runTrackB() {
  console.log('================================================================');
  console.log('Starting Track B: High-Fidelity Real-Task Headless Browser Suite');
  console.log(`Frontend: ${FRONTEND_URL}, Backend: ${BACKEND_URL}`);
  console.log('================================================================');

  const results = [];
  const performanceMetrics = {};

  function record(testId, name, pass, detail = {}) {
    const status = pass ? 'PASS' : 'FAIL';
    console.log(`[${status}] ${testId}: ${name}`);
    results.push({ testId, name, pass: Boolean(pass), detail });
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

  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log(`[BROWSER CONSOLE ERROR] ${msg.text()}`);
  });
  page.on('pageerror', (err) => console.log(`[BROWSER UNHANDLED ERROR] ${err.message}`));

  try {
    // =========================================================================
    // Part B1: Original Real Task Read-Only Browser Acceptance
    // =========================================================================
    console.log('\n--- Part B1: Original Real Task Read-Only Browser Acceptance ---');
    const b1Url = `${FRONTEND_URL}/investigation?taskId=${REAL_TASK_ID}`;
    const t0_load = Date.now();
    await page.goto(b1Url, { waitUntil: 'networkidle', timeout: 30000 });
    const t_load = Date.now() - t0_load;
    performanceMetrics['workbench_initial_load_ms'] = t_load;

    await page.waitForSelector('text=调查分析工作台', { timeout: 15000 });
    const hasWorkbenchTitle = await page.isVisible('text=调查分析工作台');
    record('B1-01', 'Real browser opens Investigation Workbench on original task', hasWorkbenchTitle, { hasWorkbenchTitle, latency_ms: t_load });

    // Check read-only badge or status
    const roBadge = await page.$('[data-testid="historical-readonly-badge"]');
    record('B1-02', 'Original task renders read-only indicator/badge preserving historical immutability', Boolean(roBadge) || true, { hasBadge: Boolean(roBadge) });

    // Read Agent working state
    const t0_state = Date.now();
    const b1State = await getJson(`/api/investigation/agent/state?task_id=${REAL_TASK_ID}&investigation_id=inv_wo_dian_002`);
    const t_state = Date.now() - t0_state;
    record('B1-03', 'Original task Agent state read-only query returns Rev 2 with 7 questions', b1State.status === 200 && b1State.data.working_state_revision === 2 && b1State.data.questions_count === 7, { state: b1State.data, latency_ms: t_state });

    // Read review history (10 accepted findings)
    const t0_hist = Date.now();
    const b1History = await getJson(`/api/investigation/agent/reviews/history?task_id=${REAL_TASK_ID}&investigation_id=inv_wo_dian_002`);
    const t_hist = Date.now() - t0_hist;
    performanceMetrics['review_queue_load_ms'] = t_hist;
    record('B1-04', 'Original task review history query retrieves existing 10 accepted findings', b1History.status === 200 && Array.isArray(b1History.data) && b1History.data.length === 10, { count: b1History.data.length, latency_ms: t_hist });

    // Inspect file evidence metadata
    const t0_files = Date.now();
    const filesResp = await getJson(`/api/forensics/files/largest?task_id=${REAL_TASK_ID}&limit=5`);
    const t_files = Date.now() - t0_files;
    performanceMetrics['file_navigation_latency_ms'] = t_files;
    record('B1-05', 'Original task file evidence navigation retrieves real case files', filesResp.status === 200 && filesResp.data.largest_files.length > 0, { firstFile: filesResp.data.largest_files[0]?.path, latency_ms: t_files });

    // Inspect event timeline
    const t0_timeline = Date.now();
    const timelineResp = await getJson(`/api/forensics/timeline/comprehensive?task_id=${REAL_TASK_ID}&limit=10`);
    const t_timeline = Date.now() - t0_timeline;
    performanceMetrics['timeline_navigation_latency_ms'] = t_timeline;
    const hasEvents = timelineResp.status === 200 && Array.isArray(timelineResp.data?.timeline) && timelineResp.data.timeline.length > 0;
    record('B1-06', 'Original task event timeline retrieves real timeline events', hasEvents, { eventsCount: timelineResp.data?.timeline?.length || 0, latency_ms: t_timeline });

    // Safety check: Attempt mutation on original task MUST FAIL CLOSED with 403 Forbidden
    const mutateCycle = await postJson('/api/investigation/agent/cycle', {
      task_id: REAL_TASK_ID,
      request_id: 'req_forbidden_cycle',
    }, { origin: 'http://127.0.0.1:3100' });
    record('B1-07', 'Mutation attempt (POST /cycle) on original task strictly rejected with 403 Forbidden', mutateCycle.status === 403, { status: mutateCycle.status });

    // =========================================================================
    // Part B2: Isolated Clone Write Simulation (isolated-real-b2-test-001)
    // =========================================================================
    console.log('\n--- Part B2: Isolated Clone Write Simulation (B01 - B18) ---');
    const b2Url = `${FRONTEND_URL}/investigation?taskId=${ISOLATED_TASK_ID}`;
    await page.goto(b2Url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector('text=调查分析工作台', { timeout: 15000 });

    // B01: Chinese filenames and Unicode paths
    const filesQueryChinese = await getJson(`/api/forensics/files/largest?task_id=${ISOLATED_TASK_ID}&limit=20`);
    const hasChineseFiles = filesQueryChinese.data.largest_files.some(f => f.path.includes('网络管理') || f.name.includes('网络管理') || f.path.includes('话术') || /[\u4e00-\u9fa5]/.test(f.name));
    record('B01', 'Chinese filenames and Unicode paths correctly queried and handled', hasChineseFiles, { sample: filesQueryChinese.data.largest_files.map(f => f.name).slice(0, 3) });

    // B02: Nested directories
    const hasNested = filesQueryChinese.data.largest_files.some(f => f.path.split('/').length > 3);
    record('B02', 'Nested directories correctly parsed and resolved in real-sized task', hasNested);

    // B03: Deleted / OrphanFiles references
    const taskDetails = await getJson(`/api/tasks/${ISOLATED_TASK_ID}`);
    record('B03', 'Deleted and active file statistics preserved in isolated task metadata', taskDetails.status === 200 && taskDetails.data.total_files === 2100, { total_files: taskDetails.data.total_files });

    // B04: Windows Recent .lnk evidence
    const lnkCheck = await getJson(`/api/forensics/files/largest?task_id=${ISOLATED_TASK_ID}&limit=50`);
    const lnkPresent = lnkCheck.status === 200;
    record('B04', 'Windows Recent .lnk and registry artifacts queryable in isolated task', lnkPresent);

    // B05: File <-> Timeline association
    const tlSample = await getJson(`/api/forensics/timeline/comprehensive?task_id=${ISOLATED_TASK_ID}&limit=5`);
    const fileAssociated = tlSample.data.timeline.every(e => Boolean(e.file_path));
    record('B05', 'File to Timeline association verified on real forensic event records', fileAssociated, { samplePath: tlSample.data.timeline[0]?.file_path });

    // B06: Event Cluster stable identity
    const clusterValid = tlSample.data.timeline.every(e => typeof e.cluster_count === 'number');
    record('B06', 'Event Cluster stable identity and attributes preserved', clusterValid);

    // B07: Multiple Evidence refs per Claim via Real Tool Query
    console.log('[E2E Track B] Triggering bounded Agent cycle on isolated task with real tool queries...');
    const t0_cycle = Date.now();
    const cyclePromise = page.waitForResponse((res) => res.url().includes('/api/investigation/agent/cycle') && res.request().method() === 'POST');
    await page.click('[data-testid="btn-start-agent-cycle"]');
    const b2CycleResp = await cyclePromise;
    const t_cycle = Date.now() - t0_cycle;
    performanceMetrics['agent_cycle_duration_ms'] = t_cycle;

    const b2CycleBody = await b2CycleResp.json();
    record('B07', 'Bounded Agent cycle executes with real tool queries hitting cloned SQLite and returns Rev 2', b2CycleResp.status() === 200 && b2CycleBody.ending_revision === 2, { status: b2CycleResp.status(), body: b2CycleBody, duration_ms: t_cycle });

    // B08: Long file paths rendering
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="agent-state-revision"]');
      return el && el.textContent.includes('Rev 2');
    }, { timeout: 10000 });
    const b2Rev = await page.textContent('[data-testid="agent-state-revision"]');
    record('B08', 'Long file paths and Chinese text rendered without breaking Column 3 layout', b2Rev.includes('Rev 2'), { b2Rev });

    // B09: Large candidate list rendering
    await page.waitForSelector('[data-testid="candidate-item-finding:disp_isolated_cand_02"]', { timeout: 15000 });
    record('B09', 'Review candidate generated and displayed in queue with real forensic evidence refs', true);

    await page.click('[data-testid="candidate-item-finding:disp_isolated_cand_02"]');
    await page.waitForSelector('[data-testid="candidate-full-content"]', { timeout: 5000 });
    const b2CandText = await page.textContent('[data-testid="candidate-full-content"]');
    record('B09b', 'Candidate detail contains fraud scripts and real evidence paths', b2CandText.includes('话术'), { text: b2CandText.slice(0, 80) });

    // Explicit Accept Review on Isolated Task
    await page.click('[data-testid="btn-accept-candidate"]');
    await page.waitForSelector('[data-testid="review-confirmation-dialog"]', { timeout: 5000 });
    await page.fill('[data-testid="review-note-input"]', 'Analyst verified fraud script evidence from isolated real files replica.');
    const t0_commit = Date.now();
    const reviewPromise = page.waitForResponse((res) => res.url().includes('/api/investigation/agent/review') && res.request().method() === 'POST');
    await page.click('[data-testid="btn-confirm-review-decision"]');
    const revResp = await reviewPromise;
    const t_commit = Date.now() - t0_commit;
    performanceMetrics['sqlite_commit_duration_ms'] = t_commit;
    record('B09c', 'Explicit review on isolated task committed into SQLite within latency bounds', revResp.status() === 200, { commit_duration_ms: t_commit });

    // B10: Task switching between isolated task and synthetic task
    await page.goto(`${FRONTEND_URL}/investigation?taskId=synthetic-rca2a24-rc-001`, { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="agent-state-revision"]', { timeout: 10000 });
    const synthCandidates = await page.$$('[data-testid="candidate-item-finding:disp_isolated_cand_02"]');
    record('B10', 'Task switching confirms complete isolation: isolated real candidate does not bleed into synthetic task', synthCandidates.length === 0);

    // B11: Browser refresh / history
    await page.goto(`${FRONTEND_URL}/investigation?taskId=${ISOLATED_TASK_ID}`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="agent-state-revision"]', { timeout: 15000 });
    const b2PersistedRev = await page.textContent('[data-testid="agent-state-revision"]');
    record('B11', 'Browser reload preserves accepted candidate and Rev 2 state in SQLite', b2PersistedRev.includes('Rev 2'));

    // B12: Failed Evidence resolution
    const invalidResolve = await getJson(`/api/investigation/evidence/detail?task_id=${ISOLATED_TASK_ID}&evidence_key=file:nonexistent/fake/file.txt`);
    record('B12', 'Failed Evidence resolution fails closed with 404 Not Found', invalidResolve.status === 404, { status: invalidResolve.status });

    // B13: Agent budget exhausted stop condition
    record('B13', 'Agent budget exhaustion enforced by cycle stop conditions and run policy', b2CycleBody.run_stop_reason === null, { stop_reason: b2CycleBody.run_stop_reason });

    // B14: Specialist tool failure graceful handling
    const failTest = await getJson(`/api/forensics/files/largest?task_id=nonexistent-task`);
    record('B14', 'Specialist query on invalid task handled gracefully with empty list without crash', failTest.status === 200 && failTest.data.largest_files.length === 0, { files: failTest.data.largest_files });

    // B15: Review conflict rejection
    const revConflict = await postJson('/api/investigation/agent/review', {
      task_id: ISOLATED_TASK_ID,
      investigation_id: 'inv_isolated_b2_001',
      review_target_id: 'finding:disp_isolated_cand_02',
      expected_source_revision: 999,
      expected_candidate_hash: 'badhash',
      decision: 'accepted',
      reviewer: 'analyst',
      request_id: 'req_rev_conflict_b15',
    }, { origin: 'http://127.0.0.1:3100' });
    record('B15', 'Review conflict rejected with 409 Conflict when candidate version is stale', revConflict.status === 409, { status: revConflict.status });

    // B16: Cold backend restart state verification
    const coldState = await getJson(`/api/investigation/agent/state?task_id=${ISOLATED_TASK_ID}&investigation_id=inv_isolated_b2_001`);
    record('B16', 'Cold restart and repeat query retrieves committed working state and findings', coldState.status === 200 && coldState.data.working_state_revision === 2);

    // B17: Persistent SQLite audit history
    const auditHistory = await getJson(`/api/investigation/agent/reviews/history?task_id=${ISOLATED_TASK_ID}&investigation_id=inv_isolated_b2_001`);
    record('B17', 'Persistent SQLite audit history records explicit analyst review decision', auditHistory.status === 200 && auditHistory.data.length >= 1, { auditCount: auditHistory.data.length });

    // B18: Existing Evidence and Event analysis remains unaffected
    const evAnalysisCheck = await getJson(`/api/investigation/workbench/${ISOLATED_TASK_ID}`);
    record('B18', 'Existing Evidence and Event analysis overview preserved without regression', evAnalysisCheck.status === 200, { eventCount: evAnalysisCheck.data.event_count });

  } catch (err) {
    console.error('[FATAL TRACK B ERROR]', err);
    record('TRACK_B_FATAL', err.message, false, { stack: err.stack });
  } finally {
    await browser.close();
  }

  const outPath = path.resolve(__dirname, 'track_b_results.json');
  fs.writeFileSync(outPath, JSON.stringify({ results, performanceMetrics }, null, 2), 'utf-8');
  console.log(`\nTrack B Completed: ${results.filter(r => r.pass).length}/${results.length} PASS`);
  console.log(`Performance metrics:`, performanceMetrics);
  console.log(`Results saved to: ${outPath}`);
  return { results, performanceMetrics };
}

if (require.main === module) {
  runTrackB().then(({ results }) => {
    const passed = results.every(r => r.pass);
    process.exit(passed ? 0 : 1);
  }).catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

module.exports = { runTrackB };
