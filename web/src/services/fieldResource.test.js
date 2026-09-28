import { afterEach, expect, test, vi } from 'vitest';
import { openFieldResource } from './fieldResource';

vi.mock('../config/runtime', () => ({ FIELD_AUTH_ENABLED: true }));
vi.mock('./fieldSession', () => ({ getFieldToken: () => 'synthetic-user-token' }));
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

test('source download uses user bearer and never fetches external URL', async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['synthetic']) });
  vi.stubGlobal('fetch', fetcher);
  const NativeURL = URL;
  vi.stubGlobal('URL', class extends NativeURL {
    static createObjectURL() { return 'blob:synthetic'; }
    static revokeObjectURL() {}
  });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await openFieldResource('/python/api/android-report/imports/abc/source-page', { downloadName: 'source.txt' });
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-user-token');
  expect(fetcher.mock.calls[0][1].redirect).toBe('error');
  await expect(openFieldResource('https://example.invalid/leak')).rejects.toThrow(/controlled entry/);
  expect(fetcher).toHaveBeenCalledTimes(1);
  click.mockRestore();
});
