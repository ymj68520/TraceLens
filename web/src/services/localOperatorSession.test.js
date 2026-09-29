import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { getLocalOperatorSession, localReturnPath } from './localOperatorSession';
import { isLocalOperatorOrigin } from '../config/runtime';

const policy = vi.hoisted(() => ({ enabled: true }));
vi.mock('../config/runtime', async (original) => ({
  ...await original(), get LOCAL_AUTO_SESSION_ENABLED() { return policy.enabled; },
}));
beforeEach(() => {
  policy.enabled = true;
  vi.stubGlobal('window', { location: { origin: 'http://127.0.0.1:8666' } });
  vi.stubGlobal('fetch', vi.fn());
});
afterEach(() => vi.unstubAllGlobals());
const session = { access_token: 'unit-signed-session', token_type: 'bearer',
  principal: { id: 'local-auto-operator', role: 'admin' } };

test.each(['http://localhost:8666', 'http://127.0.0.1:8666'])('permits exact loopback UI origin %s', (origin) => {
  expect(isLocalOperatorOrigin(origin)).toBe(true);
});
test.each(['http://192.168.1.2:8666', 'http://evil.example:8666', 'http://localhost:8090',
  'https://localhost:8666', 'http://user:pass@localhost:8666', 'null'])('rejects non-profile origin %s', (origin) => {
  expect(isLocalOperatorOrigin(origin)).toBe(false);
});
test('uses one same-origin POST; ships no password and deduplicates strict-mode callers', async () => {
  fetch.mockResolvedValue({ ok: true, json: async () => session });
  const first = getLocalOperatorSession();
  expect(getLocalOperatorSession()).toBe(first);
  expect(await first).toEqual(session);
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch).toHaveBeenCalledWith('/_local/session', expect.objectContaining({
    method: 'POST', body: '{}', cache: 'no-store', redirect: 'error', credentials: 'same-origin',
  }));
  expect(JSON.stringify(fetch.mock.calls)).not.toContain('password');
});
test('disabled profile never requests automatic credentials', async () => {
  policy.enabled = false;
  await expect(getLocalOperatorSession()).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
test('remote page cannot request local entry', async () => {
  window.location.origin = 'http://192.168.31.49:8666';
  await expect(getLocalOperatorSession()).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
test.each([null, { ...session, principal: { id: 'other', role: 'admin' } },
  { ...session, access_token: '' }])('invalid response fails closed and retry is possible', async (value) => {
  fetch.mockResolvedValue({ ok: true, json: async () => value });
  await expect(getLocalOperatorSession()).rejects.toThrow();
  fetch.mockResolvedValue({ ok: true, json: async () => session });
  expect(await getLocalOperatorSession()).toEqual(session);
});
test('unavailable service does not create a session', async () => {
  fetch.mockResolvedValue({ ok: false });
  await expect(getLocalOperatorSession()).rejects.toThrow();
});
test.each(['//evil.example', 'https://evil.example', '/login', '/_local/session', '/\\evil'])('rejects unsafe return path %s', (path) => {
  expect(localReturnPath(path)).toBe('/dashboard');
});
test('keeps the exact internal Task deep link', () => {
  expect(localReturnPath('/investigation?task_id=t1')).toBe('/investigation?task_id=t1');
});
