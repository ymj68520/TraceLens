import { Copy, FileDown, FileJson } from 'lucide-react';
import Drawer, { DetailRow } from '../../components/ui/Drawer';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import { useToast } from '../../components/ui/Toast';
import { formatBytes, formatDateTime } from '../../lib/utils';
import { isRowRelevant } from './diff';
import {
  buildClusterText,
  buildFileText,
  buildTaskText,
  copyText,
  exportResultCSV,
  exportResultJSON,
  shortTaskId,
} from './exporters';
import type { DrawerTarget } from './types';

interface ResultDetailDrawerProps {
  target: DrawerTarget | null;
  onClose: () => void;
}

/** 研判结果 Drawer 详情：文件/事件簇/任务三种目标，支持复制结果文本与导出。 */
export default function ResultDetailDrawer({ target, onClose }: ResultDetailDrawerProps) {
  const toast = useToast();

  const handleCopy = async () => {
    if (!target) return;
    const text =
      target.kind === 'file'
        ? buildFileText(target.row)
        : target.kind === 'cluster'
          ? buildClusterText(target.row)
          : buildTaskText(target.snapshot);
    const ok = await copyText(text);
    if (ok) toast.success('结果文本已复制到剪贴板');
    else toast.error('复制失败，请手动选择文本复制');
  };

  const relevantOf = (t: DrawerTarget): boolean => {
    if (t.kind === 'file') return isRowRelevant(t.row.is_relevant);
    if (t.kind === 'cluster') return isRowRelevant(t.row.llm_is_relevant);
    return false;
  };

  return (
    <Drawer
      open={!!target}
      onClose={onClose}
      title={
        target?.kind === 'task' ? '研判结果详情' : target?.kind === 'cluster' ? '事件簇详情' : '文件研判详情'
      }
      description={
        target?.kind === 'task'
          ? target.snapshot.taskId
          : target?.kind === 'cluster'
            ? `${target.row.event_type ?? '—'} @ ${target.row.parent_directory || '/'}`
            : target?.row.file_path
      }
      footer={
        <div className="flex items-center gap-2">
          <Button size="sm" variant="primary" onClick={() => void handleCopy()}>
            <Copy size={13} /> 复制结果文本
          </Button>
          {target?.kind === 'task' && (
            <>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  exportResultCSV(target.snapshot);
                  toast.success(`已导出 analysis-${shortTaskId(target.snapshot.taskId)}.csv`);
                }}
              >
                <FileDown size={13} /> 导出 CSV
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  exportResultJSON(target.snapshot);
                  toast.success(`已导出 analysis-${shortTaskId(target.snapshot.taskId)}.json`);
                }}
              >
                <FileJson size={13} /> 导出 JSON
              </Button>
            </>
          )}
        </div>
      }
    >
      {target?.kind === 'file' && (
        <div>
          <DetailRow label="文件名">{target.row.file_path?.split(/[\\/]/).filter(Boolean).pop() || '—'}</DetailRow>
          <DetailRow label="文件路径" mono>{target.row.file_path || '—'}</DetailRow>
          <DetailRow label="大小">{typeof target.row.size === 'number' ? formatBytes(target.row.size) : '—'}</DetailRow>
          <DetailRow label="相关性">
            <Badge tone={relevantOf(target) ? 'success' : 'neutral'} dot>
              {relevantOf(target) ? '案情证据' : '未标记相关'}
            </Badge>
          </DetailRow>
          <DetailRow label="关键词">
            {target.row.keywords && target.row.keywords.length > 0 ? (
              <span className="flex flex-wrap gap-1">
                {target.row.keywords.map((kw) => (
                  <span key={kw} className="chip bg-ink-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400">
                    {kw}
                  </span>
                ))}
              </span>
            ) : (
              '—'
            )}
          </DetailRow>
          <DetailRow label="所属任务" mono>{target.taskId}</DetailRow>
          <div className="pt-3">
            <h4 className="section-label mb-1.5">AI 摘要</h4>
            <p className="text-xs leading-relaxed text-ink-700 dark:text-ink-200 whitespace-pre-wrap">
              {target.row.summary?.trim() || <span className="text-ink-400">（无摘要）</span>}
            </p>
          </div>
          {target.row.description?.trim() && (
            <div className="pt-3">
              <h4 className="section-label mb-1.5">补充描述</h4>
              <p className="text-xs leading-relaxed text-ink-700 dark:text-ink-200 whitespace-pre-wrap">
                {target.row.description.trim()}
              </p>
            </div>
          )}
        </div>
      )}

      {target?.kind === 'cluster' && (
        <div>
          <DetailRow label="事件类型">
            <Badge tone="accent">{target.row.event_type || '—'}</Badge>
          </DetailRow>
          <DetailRow label="目录" mono>{target.row.parent_directory || '/'}</DetailRow>
          <DetailRow label="时间戳" mono>
            {target.row.timestamp != null ? String(target.row.timestamp) : '—'}
          </DetailRow>
          <DetailRow label="相关性">
            <Badge tone={relevantOf(target) ? 'success' : 'neutral'} dot>
              {relevantOf(target) ? '相关' : '不相关'}
            </Badge>
          </DetailRow>
          <DetailRow label="所属任务" mono>{target.taskId}</DetailRow>
          <div className="pt-3">
            <h4 className="section-label mb-1.5">AI 摘要</h4>
            <p className="text-xs leading-relaxed text-ink-700 dark:text-ink-200 whitespace-pre-wrap">
              {target.row.llm_summary?.trim() || <span className="text-ink-400">（无摘要）</span>}
            </p>
          </div>
        </div>
      )}

      {target?.kind === 'task' && (
        <div>
          <DetailRow label="任务 ID" mono>{target.snapshot.taskId}</DetailRow>
          <DetailRow label="镜像路径" mono>{target.snapshot.imagePath || '—'}</DetailRow>
          <DetailRow label="完成时间">{formatDateTime(target.snapshot.finishedAt)}</DetailRow>
          <DetailRow label="文件证据">{target.snapshot.descriptions.length} 项</DetailRow>
          <DetailRow label="相关文件">
            {target.snapshot.descriptions.filter((d) => isRowRelevant(d.is_relevant)).length} 项
          </DetailRow>
          <DetailRow label="事件簇">{target.snapshot.clusters.length} 项</DetailRow>
          <p className="pt-3 text-2xs text-ink-400 leading-relaxed">
            可在「对比」视图中将该结果与其他已完成结果逐字段比对，或通过底部按钮导出完整数据。
          </p>
        </div>
      )}
    </Drawer>
  );
}
