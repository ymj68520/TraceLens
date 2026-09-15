import { useCallback, useEffect, useMemo, useState } from 'react';
import { downloadJSON } from '../../lib/exportUtils';

/**
 * 线索笔记 — 纯前端持久化的调查笔记（localStorage，key 按任务隔离）。
 * 与后端 analyst note（getAnalystNote/saveAnalystNote，单一覆盖写）不同，
 * 这里的笔记是追加式的取证线索速记，支持删除与导出。
 */
export interface ClueNote {
  id: string;
  content: string;
  /** ISO 8601 创建时间，用于排序与导出。 */
  created_at: string;
  evidence_key: string | null;
  author: string | null;
}

const STORAGE_PREFIX = 'tracelens.clue-notes.';

const storageKey = (taskId: string) => `${STORAGE_PREFIX}${taskId}`;

const makeId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

/** 宽松解析：字段缺失/损坏的条目跳过，整体损坏返回空列表。 */
function loadNotes(taskId: string): ClueNote[] {
  try {
    const raw = localStorage.getItem(storageKey(taskId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) => {
      if (!isRecord(item) || typeof item.content !== 'string' || !item.content.trim()) return [];
      return [{
        id: typeof item.id === 'string' && item.id ? item.id : makeId(),
        content: item.content,
        created_at: typeof item.created_at === 'string' ? item.created_at : new Date().toISOString(),
        evidence_key: typeof item.evidence_key === 'string' ? item.evidence_key : null,
        author: typeof item.author === 'string' ? item.author : null,
      }];
    });
  } catch {
    return [];
  }
}

export function useClueNotes(taskId: string | null) {
  const [notes, setNotes] = useState<ClueNote[]>([]);

  // 切换任务时重新载入对应笔记。
  useEffect(() => {
    setNotes(taskId ? loadNotes(taskId) : []);
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    try {
      localStorage.setItem(storageKey(taskId), JSON.stringify(notes));
    } catch {
      // 配额不足等写入失败不影响界面使用。
    }
  }, [taskId, notes]);

  const addNote = useCallback((content: string, evidenceKey: string | null): boolean => {
    const text = content.trim();
    if (!text) return false;
    const note: ClueNote = {
      id: makeId(),
      content: text,
      created_at: new Date().toISOString(),
      evidence_key: evidenceKey,
      author: localStorage.getItem('auth_user'),
    };
    setNotes((prev) => [note, ...prev]);
    return true;
  }, []);

  const removeNote = useCallback((id: string) => {
    setNotes((prev) => prev.filter((n) => n.id !== id));
  }, []);

  /** 时间戳倒序（最新在前）。 */
  const sortedNotes = useMemo(
    () => [...notes].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [notes],
  );

  const exportNotes = useCallback(() => {
    if (!taskId || sortedNotes.length === 0) return false;
    downloadJSON(
      {
        task_id: taskId,
        exported_at: new Date().toISOString(),
        count: sortedNotes.length,
        notes: sortedNotes,
      },
      `clue-notes-${taskId}`,
    );
    return true;
  }, [taskId, sortedNotes]);

  return { notes: sortedNotes, addNote, removeNote, exportNotes };
}
