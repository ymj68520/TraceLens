/**
 * ReportReaderContent
 * 按节点 kind 渲染正文：overview / case / evidence_info / device_info /
 * contacts / sms / call_logs / locations / apps / records / chapter。
 */
import { useMemo, useState } from 'react';
import { renderCaseMarkdown } from '../markdownRenderer.jsx';
import CaseInfoSection from './sections/CaseInfoSection';
import EvidenceInfoSection from './sections/EvidenceInfoSection';
import DeviceInfoSection from './sections/DeviceInfoSection';
import SmsThreads from './sections/SmsThreads';
import GenericArtifactTable from './sections/GenericArtifactTable';

function Badge({ children, className = '' }) {
  return <span className={`inline-block px-1.5 py-0.5 text-[10px] font-semibold rounded ${className}`}>{children}</span>;
}

function fileSize(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function RowDetail({ record }) {
  const [open, setOpen] = useState(false);
  const extra = Object.entries(record)
    .filter(([k]) => !['_category', 'name', 'path', 'category', 'size', 'is_deleted', 'md5'].includes(k))
    .filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!extra.length) return null;
  return (
    <div className="mt-1">
      <button type="button" onClick={() => setOpen((o) => !o)} className="text-[10px] text-primary-600 hover:underline">
        {open ? '收起 ▲' : '详情 ▼'}
      </button>
      {open && (
        <dl className="mt-1 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
          {extra.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-slate-400">{k}</dt>
              <dd className="break-words text-slate-700 dark:text-slate-200">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function RecordsTable({ pageData }) {
  const records = pageData?.records || [];
  if (!records.length) {
    return <p className="p-6 text-center text-sm text-slate-500">该分类暂无记录。</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
      <table className="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-700">
        <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          <tr>
            <th className="px-3 py-2 font-semibold w-10">#</th>
            <th className="px-3 py-2 font-semibold">路径 / 标题</th>
            <th className="px-3 py-2 font-semibold">类型</th>
            <th className="px-3 py-2 font-semibold">大小</th>
            <th className="px-3 py-2 font-semibold">状态</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-700 dark:bg-slate-900/70">
          {records.map((r, i) => {
            const title = r.path || r.title || r.name || r.file_path || '—';
            const deleted = r.is_deleted === 1 || r.data_state === 'deleted';
            return (
              <tr key={`${r.id ?? i}-${i}`} className="align-top">
                <td className="px-3 py-2 text-slate-400">{(pageData.page - 1) * pageData.page_size + i + 1}</td>
                <td className="px-3 py-2 min-w-48 max-w-md break-all">
                  <p className="font-medium text-slate-800 dark:text-slate-100">{title}</p>
                  {r.md5 && <p className="mt-0.5 text-[10px] text-slate-400 font-mono">md5: {r.md5}</p>}
                  <RowDetail record={r} />
                </td>
                <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{r.category || r.event_type || ''}</td>
                <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{fileSize(r.size ?? r.file_size)}</td>
                <td className="px-3 py-2">
                  {deleted
                    ? <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">已删除</Badge>
                    : <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">存在</Badge>}
                  {(r.scene_relevant === 1 || r.llm_is_relevant === 1) && (
                    <Badge className="ml-1 bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">相关</Badge>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ReportReaderContent({
  node, report, pageData, loading, taskId, metadata, onEditMetadata,
}) {
  const markdownCtx = useMemo(() => ({ activeContextId: taskId, navigate: () => {}, scrollToFile: () => {} }), [taskId]);

  if (!node) return null;

  if (node.kind === 'overview') {
    return (
      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="text-lg font-bold text-slate-900 dark:text-white">报告概览</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div><dt className="text-xs text-slate-500">任务 ID</dt><dd className="font-mono break-all text-slate-800 dark:text-slate-100">{report.metadata.task_id}</dd></div>
          {report.metadata.image_path && <div><dt className="text-xs text-slate-500">镜像路径</dt><dd className="break-all text-slate-800 dark:text-slate-100">{report.metadata.image_path}</dd></div>}
          {report.metadata.files_db && <div><dt className="text-xs text-slate-500">文件数据库</dt><dd className="break-all text-slate-800 dark:text-slate-100">{report.metadata.files_db}</dd></div>}
          {report.metadata.events_db && <div><dt className="text-xs text-slate-500">事件数据库</dt><dd className="break-all text-slate-800 dark:text-slate-100">{report.metadata.events_db}</dd></div>}
          {report.metadata.generated_at && <div><dt className="text-xs text-slate-500">报告生成时间</dt><dd className="text-slate-800 dark:text-slate-100">{report.metadata.generated_at}</dd></div>}
          {report.metadata.platforms?.length > 0 && (
            <div><dt className="text-xs text-slate-500">检测平台</dt><dd className="text-slate-800 dark:text-slate-100">{report.metadata.platforms.join('、')}</dd></div>
          )}
        </dl>
        <p className="text-xs text-slate-500 dark:text-slate-400">从左侧目录选择章节查看证据记录、时间线或智能研判结论。</p>
      </section>
    );
  }

  if (node.kind === 'case') {
    return <CaseInfoSection metadata={metadata} onEdit={onEditMetadata} />;
  }

  if (node.kind === 'evidence_info') {
    return <EvidenceInfoSection metadata={metadata} onEdit={onEditMetadata} />;
  }

  if (node.kind === 'device_info') {
    return <DeviceInfoSection pageData={pageData} />;
  }

  if (node.kind === 'chapter') {
    const markdown = pageData?.records?.[0]?.markdown || '';
    return (
      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="text-lg font-bold text-slate-900 dark:text-white">{node.title}</h2>
        {loading ? <p className="text-sm text-slate-500">加载中…</p>
          : markdown ? renderCaseMarkdown(markdown, markdownCtx)
            : <p className="text-sm text-slate-500">暂无该章节内容。</p>}
      </section>
    );
  }

  // SMS keeps its specialized conversation-bubble view (Android only).
  if (node.id === 'sms') return <SmsThreads pageData={pageData} />;

  // Platform artifact sections (contacts/call_logs/apps/locations/win_*/linux_*)
  // — all rendered by the generic table via the column registry. New backend
  // sections need no frontend change.
  if (node.kind === 'records' && node.id !== 'evidence.files' && node.id !== 'timeline') {
    return <GenericArtifactTable sectionId={node.id} title={node.title} pageData={pageData} />;
  }

  // Generic records (evidence.files / timeline)
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-900 dark:text-white">{node.title}</h2>
        {node.stats && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            共 {node.stats.total} 条{node.stats.deleted ? ` · 删除 ${node.stats.deleted}` : ''}{node.stats.relevant ? ` · 相关 ${node.stats.relevant}` : ''}
          </span>
        )}
      </div>
      {loading ? <p className="p-6 text-center text-sm text-slate-500">加载中…</p>
        : <RecordsTable pageData={pageData} />}
    </section>
  );
}
