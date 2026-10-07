// Synthetic, same-origin browser regression. No mock Task or RAID API.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../web/package.json', import.meta.url));
const puppeteer = require('puppeteer');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (fs.readlinkSync('/proc/self/ns/net') === fs.readlinkSync('/proc/1/ns/net')) throw new Error('private netns required');
for (const value of [config.cpp, config.python]) {
  const u = new URL(value);
  if (u.protocol !== 'http:' || u.hostname !== '127.0.0.1' || !u.port || ['8666', '8090', '8091'].includes(u.port)) throw new Error('synthetic origin required');
}
const dist = fs.realpathSync(config.dist);
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://synthetic').pathname;
  if (pathname.startsWith('/python/') || pathname.startsWith('/api/')) {
    const python = pathname.startsWith('/python/');
    const target = new URL(python ? request.url.slice(7) : request.url, python ? config.python : config.cpp);
    const upstream = http.request(target, { method: request.method, headers: { ...request.headers, host: target.host } }, (res) => {
      response.writeHead(res.statusCode, res.headers); res.pipe(response);
    });
    upstream.on('error', () => { response.writeHead(502); response.end(); }); request.pipe(upstream); return;
  }
  const candidate = path.resolve(dist, '.' + decodeURIComponent(pathname));
  if (!candidate.startsWith(dist + path.sep)) { response.writeHead(400); response.end(); return; }
  const file = fs.existsSync(candidate) && fs.statSync(candidate).isFile() ? candidate : path.join(dist, 'index.html');
  response.writeHead(200, { 'Content-Type': ({'.js':'application/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.html':'text/html'})[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(response);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const result = { mode: 'ISOLATED_TEST', backend: 'REAL_CPP_PYTHON', standalone_raid_page: false, routes: [], page_errors: [], api_failures: [] };
try {
  browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1080 });
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = request.url();
    if (url.startsWith(origin + '/') || /^(data:|blob:|about:)/.test(url)) request.continue();
    else request.abort();
  });
  page.on('pageerror', error => result.page_errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 400 && new URL(response.url()).pathname.includes('/api/')) {
      result.api_failures.push({ path: new URL(response.url()).pathname, status: response.status() });
    }
  });
  await page.goto(origin + '/login', { waitUntil: 'networkidle2' });
  await page.type('input[type=text]', config.username);
  await page.type('input[type=password]', config.password);
  await page.click('button[type=submit]');
  await page.waitForFunction(() => location.pathname === '/dashboard');
  // SPA navigation preserves the real in-memory authenticated session.
  const visit = async target => {
    await page.evaluate(target => { window.history.pushState({}, '', target); window.dispatchEvent(new PopStateEvent('popstate')); }, target);
    await page.waitForFunction(target => location.pathname + location.search === target, {}, target);
  };
  await visit('/tasks');
  await page.waitForFunction(() => document.body.innerText.includes('RAID5'));
  const click = async text => {
    const clicked = await page.evaluate(text => {
      const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text);
      if (!button || button.disabled) return false; button.click(); return true;
    }, text);
    if (!clicked) throw new Error(`button unavailable: ${text}`);
  };
  await click('➕ Create Task');
  await page.waitForSelector('form select');
  await page.select('form select', 'raid');
  await page.waitForSelector('[data-testid=raid-image-source] input[type=checkbox]');
  await page.evaluate(() => document.querySelectorAll('[data-testid=raid-image-source] input[type=checkbox]').forEach(b => b.click()));
  await click('识别成员布局');
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '确认并准备系统镜像' && !b.disabled), { timeout: 120000 });
  await click('确认并准备系统镜像');
  await page.waitForFunction(() => document.querySelector('[data-testid=raid-image-source]')?.innerText.includes('系统镜像准备完成'), { timeout: 120000 });
  result.routes.push({ path: '/tasks', modal: 'existing_create_task', source: 'raid', inference_prepare: 'PASS' });
  // Close only the modal; the API regression already created/validated a Task.
  await click('Cancel');
  await visit(`/files?task_id=${config.task_id}`);
  await page.waitForFunction(() => document.body.innerText.includes('case-note.txt'), { timeout: 30000 });
  await page.waitForSelector('details summary');
  await page.evaluate(() => [...document.querySelectorAll('summary')].find(s => s.textContent === 'RAID 镜像来源')?.click());
  await page.waitForFunction(() => document.body.innerText.includes('来源清单 SHA-256'));
  result.routes.push({ path: '/files', known_file: 'case-note.txt', raid_source: 'PASS' });
  if (await page.$('a[href="/raid"]')) throw new Error('standalone RAID navigation was added');
  if (result.page_errors.length) throw new Error('browser runtime error');
  const expected = new Set(['/python/api/llm/cases', '/python/api/llm/status', '/python/api/graphiti/status']);
  result.expected_ai_disabled = result.api_failures.filter(item => item.status === 503 && expected.has(item.path));
  result.api_failures = result.api_failures.filter(item => !(item.status === 503 && expected.has(item.path)));
  if (result.api_failures.length) throw new Error('unexpected API failure');
  // Optional service failures are retained as evidence, not silently hidden.
  result.status = 'PASS';
  fs.writeFileSync(config.output, JSON.stringify(result, null, 2));
  process.stdout.write(JSON.stringify({ browser_status: result.status, routes: result.routes, api_failures: result.api_failures }) + '\n');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
