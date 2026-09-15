/**
 * 研判结果导出与复制：CSV（analysis-<taskid前8>.csv）、JSON、纯文本剪贴板。
 */
import { downloadCSV, downloadJSON } from '../../lib/exportUtils';
import { formatDateTime } from '../../lib/utils';
import { isRowRelevant } from './diff';
import type { ClusterRow, LlmDescriptionRow, TaskResultSnapshot } from './types';

export const shortTaskId = (taskId: string): string => taskId.slice(0, 8);

export const snapshotLabel = (snapshot: TaskResultSnapshot): string => {
  const name = (snapshot.imagePath ?? '').split(/[\\/]/).filter(Boolean).pop();
  return name ? `${name}（${shortTaskId(snapshot.taskId)}）` : shortTaskId(snapshot.taskId);
};

export const relevantFileCount = (descriptions: LlmDescriptionRow[]): number =>
  descriptions.filter((d) => isRowRelevant(d.is_relevant)).length;

/** 导出单个任务的文件研判结果为 CSV。 */
export function exportResultCSV(snapshot: TaskResultSnapshot): void {
  const rows = snapshot.descriptions.map((d) => ({
    file_path: d.file_path ?? '',
    summary: d.summary ?? '',
    description: d.description ?? '',
    keywords: (d.keywords ?? []).join('; '),
    is_relevant: isRowRelevant(d.is_relevant) ? 1 : 0,
    size: d.size ?? '',
  }));
  downloadCSV(
    rows,
    `analysis-${shortTaskId(snapshot.taskId)}.csv`,
    [
      { key: 'file_path', label: '文件路径' },
      { key: 'summary', label: 'AI 摘要' },
      { key: 'description', label: '补充描述' },
      { key: 'keywords', label: '关键词' },
      { key: 'is_relevant', label: '是否相关' },
      { key: 'size', label: '大小(字节)' },
    ],
  );
}

/** 导出单个任务完整研判结果（文件 + 事件簇）为 JSON。 */
export function exportResultJSON(snapshot: TaskResultSnapshot): void {
  downloadJSON(
    {
      task_id: snapshot.taskId,
      image_path: snapshot.imagePath ?? null,
      exported_at: new Date().toISOString(),
      file_count: snapshot.descriptions.length,
      cluster_count: snapshot.clusters.length,
      descriptions: snapshot.descriptions,
      clusters: snapshot.clusters,
    },
    `analysis-${shortTaskId(snapshot.taskId)}.json`,
  );
}

/* --------------------------- 纯文本（复制） ----------------------------- */

export function buildFileText(row: LlmDescriptionRow): string {
  const lines = [
    `文件：${row.file_path ?? '—'}`,
    `相关性：${isRowRelevant(row.is_relevant) ? '相关' : '不相关'}`,
    `大小：${typeof row.size === 'number' ? `${row.size} 字节` : '—'}`,
    `关键词：${(row.keywords ?? []).join('、') || '—'}`,
    `摘要：${row.summary?.trim() || '—'}`,
  ];
  if (row.description?.trim()) lines.push(`描述：${row.description.trim()}`);
  return lines.join('\n');
}

export function buildClusterText(row: ClusterRow): string {
  return [
    `事件簇：${row.event_type ?? '—'} @ ${row.parent_directory || '/'}`,
    `时间戳：${row.timestamp ?? '—'}`,
    `相关性：${isRowRelevant(row.llm_is_relevant) ? '相关' : '不相关'}`,
    `摘要：${row.llm_summary?.trim() || '—'}`,
  ].join('\n');
}

export function buildTaskText(snapshot: TaskResultSnapshot): string {
  const header = [
    `TraceLens 研判结果`,
    `任务：${snapshot.taskId}`,
    `镜像：${snapshot.imagePath ?? '—'}`,
    `导出时间：${formatDateTime(Date.now())}`,
    `文件证据 ${snapshot.descriptions.length} 项（相关 ${relevantFileCount(snapshot.descriptions)} 项），事件簇 ${snapshot.clusters.length} 项`,
    '',
  ].join('\n');
  const files = snapshot.descriptions.map((d) => buildFileText(d)).join('\n\n');
  const clusters = snapshot.clusters.length
    ? `\n\n—— 事件簇 ——\n${snapshot.clusters.map((c) => buildClusterText(c)).join('\n\n')}`
    : '';
  return header + files + clusters;
}

/** 剪贴板写入，带 execCommand 兜底；返回是否成功。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}
