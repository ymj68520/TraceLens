import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  APP_EVENTS_STORAGE_KEY,
  MAX_APP_EVENTS,
  clearAppEvents,
  emitAppEvent,
  getAppEvents,
  subscribeAppEvents,
} from '../lib/appEvents';
import type { AppEvent } from '../lib/appEvents';

beforeEach(() => {
  localStorage.clear();
  clearAppEvents();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('emit / subscribe lifecycle', () => {
  it('buffers newest-first and fills id/ts when omitted', () => {
    const before = Date.now();
    const first = emitAppEvent({ kind: 'success', title: 'e1' });
    const second = emitAppEvent({ kind: 'error', title: 'e2', detail: 'boom' });

    expect(getAppEvents().map((e) => e.title)).toEqual(['e2', 'e1']);
    expect(first.id).toMatch(/^evt_[a-z0-9]+_[a-z0-9]+$/);
    expect(first.ts).toBeGreaterThanOrEqual(before);
    expect(first.ts).toBeLessThanOrEqual(Date.now());
    expect(second.detail).toBe('boom');
    expect(getAppEvents()[0]).toBe(second);
  });

  it('honours explicit id/ts from the producer', () => {
    const evt = emitAppEvent({ kind: 'info', title: 'fixed', id: 'custom-id', ts: 12345 });
    expect(evt.id).toBe('custom-id');
    expect(evt.ts).toBe(12345);
    expect(getAppEvents()[0]).toEqual({ id: 'custom-id', kind: 'info', title: 'fixed', ts: 12345 });
  });

  it('unsubscribe stops delivery while other listeners keep working', () => {
    const seen: AppEvent[] = [];
    const unsubscribe = subscribeAppEvents((evt) => seen.push(evt));
    const evt = emitAppEvent({ kind: 'success', title: 'delivered' });

    expect(seen).toHaveLength(1);
    expect(seen[0]).toBe(evt);

    unsubscribe();
    emitAppEvent({ kind: 'success', title: 'after' });
    expect(seen).toHaveLength(1);
    expect(seen[0].title).toBe('delivered');
  });

  it('a throwing listener does not starve the others', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const received: string[] = [];
    const unsubscribeBad = subscribeAppEvents(() => {
      throw new Error('listener bug');
    });
    const unsubscribeGood = subscribeAppEvents((evt) => received.push(evt.title));

    const evt = emitAppEvent({ kind: 'info', title: 'still-fires' });
    expect(received).toEqual(['still-fires']);
    expect(evt.title).toBe('still-fires');
    expect(errorSpy).toHaveBeenCalled();

    // Do not leak the broken listener into other tests.
    unsubscribeBad();
    unsubscribeGood();
  });

  it('caps the buffer at MAX_APP_EVENTS, keeping the newest', () => {
    for (let i = 0; i < MAX_APP_EVENTS + 10; i += 1) {
      emitAppEvent({ kind: 'info', title: `e${i}` });
    }
    const snapshot = getAppEvents();
    expect(snapshot).toHaveLength(MAX_APP_EVENTS);
    expect(snapshot[0].title).toBe(`e${MAX_APP_EVENTS + 9}`);
    expect(snapshot[MAX_APP_EVENTS - 1].title).toBe('e10');
    const stored = JSON.parse(localStorage.getItem(APP_EVENTS_STORAGE_KEY) ?? '[]') as AppEvent[];
    expect(stored).toHaveLength(MAX_APP_EVENTS);
  });

  it('persists every emit to localStorage', () => {
    emitAppEvent({ kind: 'success', title: 'persisted', detail: 'd' });
    const stored = JSON.parse(localStorage.getItem(APP_EVENTS_STORAGE_KEY) ?? '[]') as AppEvent[];
    expect(stored[0]).toMatchObject({ kind: 'success', title: 'persisted', detail: 'd' });
  });

  it('clearAppEvents wipes memory and storage', () => {
    emitAppEvent({ kind: 'info', title: 'x' });
    clearAppEvents();
    expect(getAppEvents()).toEqual([]);
    expect(JSON.parse(localStorage.getItem(APP_EVENTS_STORAGE_KEY) ?? 'null')).toEqual([]);
  });

  it('survives a failing localStorage write (quota / privacy mode)', () => {
    const setSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError');
    });
    expect(() => emitAppEvent({ kind: 'info', title: 'quota' })).not.toThrow();
    expect(getAppEvents()).toHaveLength(1);
    setSpy.mockRestore();
  });
});

describe('localStorage hydration', () => {
  /** Import a pristine copy of the module so it re-runs its load-time hydration. */
  async function freshModule(): Promise<typeof import('../lib/appEvents')> {
    vi.resetModules();
    return import('../lib/appEvents');
  }

  it('hydrates previously persisted events', async () => {
    localStorage.setItem(
      APP_EVENTS_STORAGE_KEY,
      JSON.stringify([
        { id: 'a', kind: 'success', title: 'kept-a', ts: 100, detail: 'with-detail' },
        { id: 'b', kind: 'error', title: 'kept-b', ts: 200 },
      ]),
    );
    const mod = await freshModule();
    expect(mod.getAppEvents()).toEqual([
      { id: 'a', kind: 'success', title: 'kept-a', ts: 100, detail: 'with-detail' },
      { id: 'b', kind: 'error', title: 'kept-b', ts: 200 },
    ]);
  });

  it('drops dirty entries field by field', async () => {
    localStorage.setItem(
      APP_EVENTS_STORAGE_KEY,
      JSON.stringify([
        'not-an-object',
        null,
        { id: 7, kind: 'success', title: 'bad-id', ts: 1 },
        { id: 'k', kind: 'success', title: 9, ts: 1 },
        { id: 'k', kind: 'success', title: 'bad-ts', ts: '1' },
        { id: 'k', kind: 'bogus-kind', title: 'bad-kind', ts: 1 },
        { id: 'ok', kind: 'info', title: 'valid', ts: 5, detail: 123 },
      ]),
    );
    const mod = await freshModule();
    expect(mod.getAppEvents()).toEqual([{ id: 'ok', kind: 'info', title: 'valid', ts: 5 }]);
  });

  it('treats a non-array payload as empty', async () => {
    localStorage.setItem(APP_EVENTS_STORAGE_KEY, JSON.stringify({ nope: true }));
    const mod = await freshModule();
    expect(mod.getAppEvents()).toEqual([]);
  });

  it('treats corrupted JSON as empty and warns', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    localStorage.setItem(APP_EVENTS_STORAGE_KEY, '{not json');
    const mod = await freshModule();
    expect(mod.getAppEvents()).toEqual([]);
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('caps hydration at MAX_APP_EVENTS entries', async () => {
    const persisted = Array.from({ length: MAX_APP_EVENTS + 5 }, (_, i) => ({
      id: `id-${i}`,
      kind: 'info',
      title: `t${i}`,
      ts: i,
    }));
    localStorage.setItem(APP_EVENTS_STORAGE_KEY, JSON.stringify(persisted));
    const mod = await freshModule();
    expect(mod.getAppEvents()).toHaveLength(MAX_APP_EVENTS);
  });
});
