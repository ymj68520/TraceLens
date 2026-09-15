import { useCallback, useEffect, useMemo, useState } from 'react';
import { clearAppEvents, getAppEvents, subscribeAppEvents } from '../lib/appEvents';
import type { AppEvent } from '../lib/appEvents';

const READ_AT_STORAGE_KEY = 'app.events.readAt';

function loadReadAt(): number {
  try {
    const raw = localStorage.getItem(READ_AT_STORAGE_KEY);
    const parsed = raw === null ? Number.NaN : Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  } catch {
    // Storage unavailable — treat everything as unread for this session.
    return 0;
  }
}

function persistReadAtValue(ts: number): void {
  try {
    localStorage.setItem(READ_AT_STORAGE_KEY, String(ts));
  } catch {
    // Quota or privacy mode — read state stays in memory only.
  }
}

export interface UseAppNotificationsResult {
  events: AppEvent[];
  unreadCount: number;
  /** Events with `ts <= readAt` count as read (timestamp comparison). */
  readAt: number;
  markAllRead: () => void;
  /** Marks one event — and everything before it — as read. */
  markRead: (id: string) => void;
  clearAll: () => void;
}

/**
 * Bridges the appEvents bus into React state and tracks unread state via a
 * persisted 'last read at' timestamp, so unread markers survive reloads
 * without writing one flag per event.
 */
export function useAppNotifications(): UseAppNotificationsResult {
  const [events, setEvents] = useState<AppEvent[]>(() => getAppEvents());
  const [readAt, setReadAt] = useState<number>(() => loadReadAt());

  useEffect(
    () =>
      subscribeAppEvents(() => {
        // The bus is the single source of truth — always mirror it.
        setEvents(getAppEvents());
      }),
    [],
  );

  const applyReadAt = useCallback((ts: number) => {
    setReadAt(ts);
    persistReadAtValue(ts);
  }, []);

  const markAllRead = useCallback(() => applyReadAt(Date.now()), [applyReadAt]);

  const markRead = useCallback(
    (id: string) => {
      const target = events.find((evt) => evt.id === id);
      if (!target) return;
      applyReadAt(Math.max(readAt, target.ts));
    },
    [applyReadAt, events, readAt],
  );

  const clearAll = useCallback(() => {
    clearAppEvents();
    setEvents([]);
  }, []);

  const unreadCount = useMemo(
    () => events.reduce((count, evt) => (evt.ts > readAt ? count + 1 : count), 0),
    [events, readAt],
  );

  return { events, unreadCount, readAt, markAllRead, markRead, clearAll };
}

export default useAppNotifications;
