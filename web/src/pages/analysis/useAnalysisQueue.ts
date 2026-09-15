/**
 * 批量研判队列引擎：顺序执行、并发上限（默认 2）、移除/重试/清空、
 * 全部结算后回调汇总。runner 通过 ref 始终取最新闭包，避免陈旧状态。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../../lib/utils';
import type { QueueEntry, QueueItem, QueueRunResult } from './types';

export interface QueueSettledSummary {
  total: number;
  done: number;
  failed: number;
}

/** 队列唯一键：同任务同文件不重复入队。 */
export function queueKey(item: QueueItem): string {
  return item.kind === 'task' ? `task:${item.taskId}` : `file:${item.taskId}:${item.filePath}`;
}

interface Options {
  runner: (item: QueueItem) => Promise<QueueRunResult>;
  onItemFailed?: (entry: QueueEntry) => void;
  onAllSettled?: (summary: QueueSettledSummary) => void;
  concurrency?: number;
}

export function useAnalysisQueue({ runner, onItemFailed, onAllSettled, concurrency = 2 }: Options) {
  const [entries, setEntriesState] = useState<QueueEntry[]>([]);
  const entriesRef = useRef<QueueEntry[]>([]);
  const runnerRef = useRef(runner);
  const failedRef = useRef(onItemFailed);
  const settledRef = useRef(onAllSettled);
  const settledSigRef = useRef('');

  useEffect(() => {
    runnerRef.current = runner;
  }, [runner]);
  useEffect(() => {
    failedRef.current = onItemFailed;
  }, [onItemFailed]);
  useEffect(() => {
    settledRef.current = onAllSettled;
  }, [onAllSettled]);

  /** 同步更新 ref + state，保证异步回调里读到最新队列。 */
  const commit = useCallback((updater: (prev: QueueEntry[]) => QueueEntry[]) => {
    const next = updater(entriesRef.current);
    entriesRef.current = next;
    setEntriesState(next);
  }, []);

  const settle = useCallback(
    (id: string, patch: Partial<QueueEntry>) => {
      commit((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
    },
    [commit],
  );

  const run = useCallback(
    async (entry: QueueEntry) => {
      try {
        const result = await runnerRef.current(entry.item);
        settle(entry.id, { status: 'done', finishedAt: Date.now(), result, error: undefined });
      } catch (err) {
        const error = errorMessage(err);
        settle(entry.id, { status: 'failed', finishedAt: Date.now(), error });
        failedRef.current?.({
          ...(entriesRef.current.find((e) => e.id === entry.id) ?? entry),
          status: 'failed',
          error,
        });
      }
    },
    [settle],
  );

  /** 用空闲并发槽位启动等待中的条目；在 entries 变更后由 effect 驱动。 */
  const pump = useCallback(() => {
    const limit = Math.max(1, concurrency);
    const current = entriesRef.current;
    const free = limit - current.filter((e) => e.status === 'running').length;
    if (free <= 0) return;
    const toStart = current.filter((e) => e.status === 'pending').slice(0, free);
    if (toStart.length === 0) return;
    const ids = new Set(toStart.map((e) => e.id));
    commit((prev) =>
      prev.map((e) =>
        ids.has(e.id) ? { ...e, status: 'running', startedAt: Date.now(), error: undefined } : e,
      ),
    );
    toStart.forEach((entry) => void run(entry));
  }, [commit, concurrency, run]);

  // 任何队列变更（入队/完成/失败/移除）后立即补位。
  useEffect(() => {
    pump();
  }, [entries, pump]);

  // 队列清空（无等待/进行中）时回调一次汇总。
  useEffect(() => {
    if (entries.length === 0) return;
    if (entries.some((e) => e.status === 'pending' || e.status === 'running')) return;
    const done = entries.filter((e) => e.status === 'done').length;
    const failed = entries.filter((e) => e.status === 'failed').length;
    const sig = `${entries.length}-${done}-${failed}`;
    if (sig === settledSigRef.current) return;
    settledSigRef.current = sig;
    settledRef.current?.({ total: entries.length, done, failed });
  }, [entries]);

  /** 入队；已失败的条目自动重置为等待，其余重复条目跳过。返回 {added, retried}。 */
  const enqueue = useCallback(
    (items: QueueItem[]): { added: number; retried: number } => {
      if (items.length === 0) return { added: 0, retried: 0 };
      let added = 0;
      let retried = 0;
      commit((prev) => {
        const next = [...prev];
        for (const item of items) {
          const key = queueKey(item);
          const idx = next.findIndex((e) => e.key === key);
          if (idx >= 0) {
            if (next[idx].status === 'failed') {
              next[idx] = { ...next[idx], status: 'pending', error: undefined };
              retried += 1;
            }
            continue;
          }
          next.push({ id: key, key, item, status: 'pending' });
          added += 1;
        }
        return next;
      });
      return { added, retried };
    },
    [commit],
  );

  /** 重试失败条目。 */
  const retry = useCallback(
    (id: string) => {
      commit((prev) =>
        prev.map((e) => (e.id === id && e.status === 'failed' ? { ...e, status: 'pending', error: undefined } : e)),
      );
    },
    [commit],
  );

  /** 移除条目（进行中的不可移除，底层请求无取消通道）。 */
  const remove = useCallback(
    (id: string) => {
      commit((prev) => prev.filter((e) => !(e.id === id && e.status !== 'running')));
    },
    [commit],
  );

  /** 清空所有非进行中条目。 */
  const clear = useCallback(() => {
    commit((prev) => prev.filter((e) => e.status === 'running'));
  }, [commit]);

  return { entries, enqueue, retry, remove, clear };
}
