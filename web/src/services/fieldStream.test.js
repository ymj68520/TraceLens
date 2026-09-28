import { afterEach, expect, test, vi } from 'vitest';
import { authorizedFetch } from './fieldStream';

vi.mock('../config/runtime', () => ({ FIELD_AUTH_ENABLED: true }));
vi.mock('./fieldSession', () => ({ getFieldToken: () => 'synthetic-user-token' }));
afterEach(() => vi.unstubAllGlobals());

test('stream fetch sends only user bearer to controlled same-origin API', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal('fetch', fetcher);
  await authorizedFetch('/python/api/system/logs/cpp');
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toContain('/python/api/system/logs/cpp');
  expect(options.headers.get('Authorization')).toBe('Bearer synthetic-user-token');
  expect(options.redirect).toBe('error');
  await expect(authorizedFetch('https://example.invalid/api/system/logs/cpp')).rejects.toThrow(/controlled entry/);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
