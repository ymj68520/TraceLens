import type { ForensicTask } from '../../../types/api';
import { basename } from '../../../lib/utils';

/**
 * Task execution duration helpers.
 *
 * The C++ backend reports real execution time in **seconds** under
 * `task.timestamps.execution_time_seconds` once a task finishes. Every
 * accessor here is defensive: missing/invalid values yield null so the UI
 * can degrade gracefully instead of rendering fake zeros.
 */

export interface DurationEntry {
  id: string;
  /** Basename of the analyzed image (falls back to the raw task id). */
  image: string;
  /** Duration normalized to milliseconds. */
  ms: number;
}

export interface DurationSummary {
  /** Per-task entries sorted slowest → fastest. */
  entries: DurationEntry[];
  count: number;
  totalMs: number;
  avgMs: number;
  fastest: DurationEntry;
  slowest: DurationEntry;
}

/** Raw seconds from `timestamps.execution_time_seconds`, or null when absent. */
export const getTaskDurationSeconds = (task: unknown): number | null => {
  const t = task as { timestamps?: { execution_time_seconds?: unknown } } | null | undefined;
  const raw = t?.timestamps?.execution_time_seconds;
  const seconds = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : NaN;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds;
};

/** Same value in whole milliseconds, or null when the task has no duration. */
export const getTaskDurationMs = (task: unknown): number | null => {
  const seconds = getTaskDurationSeconds(task);
  return seconds == null ? null : Math.round(seconds * 1000);
};

/** All tasks that carry a real duration, newest-list order preserved. */
export const collectDurationEntries = (tasks: ForensicTask[]): DurationEntry[] => {
  const entries: DurationEntry[] = [];
  for (const task of tasks) {
    const ms = getTaskDurationMs(task);
    if (ms == null) continue;
    entries.push({ id: task.id, image: basename(task.image_path) || task.id, ms });
  }
  return entries;
};

/** Aggregate stats over recorded durations; null when nothing is measurable. */
export const summarizeDurations = (tasks: ForensicTask[]): DurationSummary | null => {
  const entries = collectDurationEntries(tasks);
  if (entries.length === 0) return null;
  const sorted = [...entries].sort((a, b) => b.ms - a.ms);
  const totalMs = sorted.reduce((sum, e) => sum + e.ms, 0);
  return {
    entries: sorted,
    count: sorted.length,
    totalMs,
    avgMs: Math.round(totalMs / sorted.length),
    slowest: sorted[0],
    fastest: sorted[sorted.length - 1],
  };
};
