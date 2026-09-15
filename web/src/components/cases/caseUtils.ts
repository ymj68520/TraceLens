import type { ForensicCase, ForensicTask } from '../../types/api';

/* ---------------------------------------------------------------------------
 * Shared helpers for the case management domain: status presentation maps,
 * task-progress extraction and the case-archive export payload builder.
 * ------------------------------------------------------------------------- */

export type CaseStatusTone = 'info' | 'warning' | 'success' | 'danger' | 'neutral';

export const CASE_STATUS_TONE: Record<string, CaseStatusTone> = {
  open: 'info',
  analysing: 'warning',
  completed: 'success',
  failed: 'danger',
};

export const CASE_STATUS_LABEL: Record<string, string> = {
  open: '待分析',
  analysing: '分析中',
  completed: '已完成',
  failed: '失败',
};

export const caseStatusTone = (status?: string): CaseStatusTone =>
  CASE_STATUS_TONE[status ?? 'open'] ?? 'neutral';

export const caseStatusLabel = (status?: string): string =>
  CASE_STATUS_LABEL[status ?? 'open'] ?? (status || '未知');

/**
 * Task progress arrives either as a plain number or as an analysis object
 * exposing `overall_percentage`; normalize both to 0-100.
 */
export const getTaskProgress = (task: ForensicTask): number => {
  const p = task.progress as unknown;
  if (typeof p === 'object' && p !== null) {
    return (p as { overall_percentage?: number }).overall_percentage ?? 0;
  }
  return ((task as { progress?: unknown }).progress as number) || 0;
};

/**
 * Case archive payload: case metadata plus one entry per associated task.
 * Fed to `downloadJSON` by the case detail export action.
 */
export function buildCaseArchive(forensicCase: ForensicCase, caseTasks: ForensicTask[]) {
  const c = forensicCase;
  return {
    exported_at: new Date().toISOString(),
    generator: 'TraceLens 案件档案导出',
    case: {
      id: c.id,
      name: c.name,
      description: c.description ?? '',
      status: c.status ?? 'open',
      created_at: c.created_at ?? null,
      updated_at: c.updated_at ?? null,
      task_count: (c.task_ids ?? []).length,
    },
    tasks: caseTasks.map((t) => ({
      id: t.id,
      image_path: t.image_path,
      status: t.status,
      priority: t.priority ?? 'normal',
      progress: getTaskProgress(t),
      created_at: t.created_at ?? null,
      started_at: t.started_at ?? null,
      finished_at: t.finished_at ?? null,
      error_message: t.error_message ?? null,
    })),
  };
}
