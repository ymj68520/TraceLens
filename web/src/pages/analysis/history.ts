/**
 * 最近研判历史 — localStorage 持久化（最近 20 条，整表单键存储）。
 * 供侧边栏「快速回填」：一键把历史任务重新加入批量研判队列。
 */
import { useCallback, useState } from 'react';
import type { AnalysisHistoryEntry } from './types';

const HISTORY_KEY = 'tracelens.analysis-history';
const HISTORY_LIMIT = 20;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

/** 宽松解析：字段损坏的条目跳过，整体损坏返回空列表。 */
function loadHistory(): AnalysisHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const out: AnalysisHistoryEntry[] = [];
    for (const item of parsed) {
      if (!isRecord(item) || typeof item.taskId !== 'string' || !item.taskId.trim()) continue;
      out.push({
        taskId: item.taskId,
        imagePath: typeof item.imagePath === 'string' ? item.imagePath : undefined,
        savedAt: typeof item.savedAt === 'string' ? item.savedAt : new Date().toISOString(),
        fileCount: typeof item.fileCount === 'number' ? item.fileCount : 0,
        clusterCount: typeof item.clusterCount === 'number' ? item.clusterCount : 0,
        relevantCount: typeof item.relevantCount === 'number' ? item.relevantCount : 0,
      });
    }
    return out;
  } catch {
    return [];
  }
}

function saveHistory(entries: AnalysisHistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  } catch {
    // 配额不足等写入失败不影响界面使用。
  }
}

export function useAnalysisHistory() {
  const [entries, setEntries] = useState<AnalysisHistoryEntry[]>(() => loadHistory());

  /** 记录一次任务研判完成；同任务去重置顶，超过 20 条截断。 */
  const record = useCallback((entry: AnalysisHistoryEntry) => {
    setEntries((prev) => {
      const next = [entry, ...prev.filter((e) => e.taskId !== entry.taskId)].slice(0, HISTORY_LIMIT);
      saveHistory(next);
      return next;
    });
  }, []);

  const remove = useCallback((taskId: string) => {
    setEntries((prev) => {
      const next = prev.filter((e) => e.taskId !== taskId);
      saveHistory(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    saveHistory([]);
  }, []);

  return { entries, record, remove, clear };
}
