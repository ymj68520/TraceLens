import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useAppNotifications } from '../hooks/useAppNotifications';
import { APP_EVENTS_STORAGE_KEY, clearAppEvents, emitAppEvent } from '../lib/appEvents';

const READ_AT_KEY = 'app.events.readAt';

beforeEach(() => {
  localStorage.clear();
  clearAppEvents();
});

describe('useAppNotifications', () => {
  it('mirrors bus events into state and counts unread', () => {
    const { result } = renderHook(() => useAppNotifications());
    expect(result.current.events).toEqual([]);
    expect(result.current.unreadCount).toBe(0);

    act(() => {
      emitAppEvent({ kind: 'success', title: 'task done' });
    });
    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0].title).toBe('task done');
    expect(result.current.unreadCount).toBe(1);

    act(() => {
      emitAppEvent({ kind: 'error', title: 'task failed' });
    });
    expect(result.current.unreadCount).toBe(2);
  });

  it('markAllRead zeroes the counter and persists the read marker', () => {
    const { result } = renderHook(() => useAppNotifications());
    act(() => {
      emitAppEvent({ kind: 'info', title: 'a' });
    });
    act(() => {
      result.current.markAllRead();
    });
    expect(result.current.unreadCount).toBe(0);
    expect(result.current.readAt).toBeGreaterThan(0);
    expect(Number(localStorage.getItem(READ_AT_KEY))).toBe(result.current.readAt);

    // An event newer than the marker counts as unread again.
    // (Explicit ts: a same-millisecond Date.now() would count as read.)
    act(() => {
      emitAppEvent({ kind: 'info', title: 'new one', ts: result.current.readAt + 1000 });
    });
    expect(result.current.unreadCount).toBe(1);
  });

  it('markRead marks the event and everything older as read', () => {
    const { result } = renderHook(() => useAppNotifications());
    let olderId = '';
    let newerId = '';
    act(() => {
      olderId = emitAppEvent({ kind: 'info', title: 'older', ts: 1000 }).id;
      newerId = emitAppEvent({ kind: 'info', title: 'newer', ts: 2000 }).id;
    });
    expect(result.current.unreadCount).toBe(2);

    act(() => {
      result.current.markRead(olderId);
    });
    expect(result.current.readAt).toBe(1000);
    expect(result.current.unreadCount).toBe(1);

    act(() => {
      result.current.markRead('does-not-exist');
    });
    expect(result.current.readAt).toBe(1000);

    act(() => {
      result.current.markRead(newerId);
    });
    expect(result.current.readAt).toBe(2000);
    expect(result.current.unreadCount).toBe(0);
  });

  it('hydrates readAt from localStorage so old events stay read', () => {
    localStorage.setItem(READ_AT_KEY, '1500');
    act(() => {
      emitAppEvent({ kind: 'info', title: 'old', ts: 1000 });
      emitAppEvent({ kind: 'info', title: 'fresh', ts: 9000 });
    });
    const { result } = renderHook(() => useAppNotifications());
    expect(result.current.readAt).toBe(1500);
    expect(result.current.unreadCount).toBe(1);
    expect(result.current.events[0].title).toBe('fresh');
  });

  it('clearAll empties events and storage', () => {
    const { result } = renderHook(() => useAppNotifications());
    act(() => {
      emitAppEvent({ kind: 'success', title: 'bye' });
    });
    act(() => {
      result.current.clearAll();
    });
    expect(result.current.events).toEqual([]);
    expect(result.current.unreadCount).toBe(0);
    expect(JSON.parse(localStorage.getItem(APP_EVENTS_STORAGE_KEY) ?? 'null')).toEqual([]);
  });
});
