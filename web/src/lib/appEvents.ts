/**
 * Lightweight app-wide event bus for user-facing notifications.
 *
 * Producers call `emitAppEvent` (e.g. after a task succeeds or fails);
 * consumers (NotificationCenter / useAppNotifications) subscribe via
 * `subscribeAppEvents`. The most recent MAX_EVENTS events persist in
 * localStorage under 'app.events' so the bell still shows recent activity
 * after a page reload. Intentionally dependency-free: a Set of listeners
 * plus an in-memory newest-first list.
 */

export type AppEventKind = 'success' | 'error' | 'info';

export interface AppEvent {
  id: string;
  kind: AppEventKind;
  title: string;
  detail?: string;
  /** Epoch ms — used for relative time display and read-state comparison. */
  ts: number;
}

/** Everything except id/ts is required; the bus fills those in when omitted. */
export type AppEventInput = Omit<AppEvent, 'id' | 'ts'> & Partial<Pick<AppEvent, 'id' | 'ts'>>;

export const APP_EVENTS_STORAGE_KEY = 'app.events';
export const MAX_APP_EVENTS = 50;

const KINDS: ReadonlySet<string> = new Set(['success', 'error', 'info']);

type AppEventListener = (evt: AppEvent) => void;

const listeners = new Set<AppEventListener>();

/** Defensive parse for anything coming back out of localStorage. */
function sanitizeEvent(raw: unknown): AppEvent | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (
    typeof r.id !== 'string' ||
    typeof r.title !== 'string' ||
    typeof r.ts !== 'number' ||
    typeof r.kind !== 'string' ||
    !KINDS.has(r.kind)
  ) {
    return null;
  }
  const evt: AppEvent = { id: r.id, kind: r.kind as AppEventKind, title: r.title, ts: r.ts };
  if (typeof r.detail === 'string') evt.detail = r.detail;
  return evt;
}

function loadPersistedEvents(): AppEvent[] {
  try {
    const raw = localStorage.getItem(APP_EVENTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(sanitizeEvent)
      .filter((evt): evt is AppEvent => evt !== null)
      .slice(0, MAX_APP_EVENTS);
  } catch (err) {
    // Corrupted payload or storage unavailable — start with a clean buffer.
    console.warn('[appEvents] failed to load persisted events:', err);
    return [];
  }
}

// Module load: hydrate the buffer from the previous session.
let events: AppEvent[] = loadPersistedEvents();

function persistEvents(): void {
  try {
    localStorage.setItem(APP_EVENTS_STORAGE_KEY, JSON.stringify(events));
  } catch {
    // Quota exceeded or privacy mode — keep the in-memory copy only.
  }
}

function createEventId(): string {
  return `evt_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Publish an event: buffered newest-first, capped, persisted, broadcast. */
export function emitAppEvent(input: AppEventInput): AppEvent {
  const evt: AppEvent = {
    id: input.id ?? createEventId(),
    kind: input.kind,
    title: input.title,
    detail: input.detail,
    ts: input.ts ?? Date.now(),
  };
  events = [evt, ...events].slice(0, MAX_APP_EVENTS);
  persistEvents();
  listeners.forEach((fn) => {
    try {
      fn(evt);
    } catch (err) {
      // One broken listener must not starve the others.
      console.error('[appEvents] listener threw:', err);
    }
  });
  return evt;
}

/** Subscribe to newly emitted events; the return value unsubscribes. */
export function subscribeAppEvents(fn: AppEventListener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Snapshot of the currently buffered events (newest first). */
export function getAppEvents(): AppEvent[] {
  return [...events];
}

/** Drop every event (memory + localStorage). Read state is left untouched. */
export function clearAppEvents(): void {
  events = [];
  persistEvents();
}
