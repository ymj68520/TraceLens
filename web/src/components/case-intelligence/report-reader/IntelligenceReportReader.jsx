/**
 * IntelligenceReportReader
 *
 * 参考式证据研判报告阅读器，用于 /case-intelligence。
 * 三栏布局：左侧目录 + 中央正文 + 底部分页/搜索控制。
 * 数据来自 /api/llm/intelligence-report/{task_id}（与 /api/reports 取证快照分离）。
 *
 * 点击"研判工具"按钮会跳转到对应镜像的研判中心页面（/analysis-center?task_id=…）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ReportReaderDirectory from './ReportReaderDirectory';
import ReportReaderContent from './ReportReaderContent';
import ReportReaderPagination from './ReportReaderPagination';
import ReportReaderSearch from './ReportReaderSearch';
import ReportMetadataEditor from './ReportMetadataEditor';
import {
  getIntelligenceReport,
  getIntelligenceRecords,
  searchIntelligenceReport,
  getReportMetadata,
} from '../../../services/intelligenceReportService';

export default function IntelligenceReportReader({ taskId }) {
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState('overview');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [pageData, setPageData] = useState(null);
  const [loadingReport, setLoadingReport] = useState(true);
  const [loadingPage, setLoadingPage] = useState(false);
  const [error, setError] = useState(null);

  // case/evidence metadata (案件信息 / 证据信息)
  const [metadata, setMetadata] = useState(null);
  const [editorOpen, setEditorOpen] = useState(false);

  // search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchSubmitted, setSearchSubmitted] = useState('');
  const [searchResult, setSearchResult] = useState(null);
  const [searching, setSearching] = useState(false);

  // mobile directory drawer
  const [dirOpen, setDirOpen] = useState(false);

  const reqIdRef = useRef(0);

  // load directory + metadata
  useEffect(() => {
    let cancelled = false;
    setLoadingReport(true);
    setError(null);
    Promise.all([
      getIntelligenceReport(taskId),
      getReportMetadata(taskId).catch(() => null),
    ])
      .then(([data, meta]) => {
        if (cancelled) return;
        setReport(data);
        if (meta?.metadata) setMetadata(meta.metadata);
        setSelectedNodeId('overview');
        setPage(1);
      })
      .catch((err) => { if (!cancelled) setError(err); })
      .finally(() => { if (!cancelled) setLoadingReport(false); });
    return () => { cancelled = true; };
  }, [taskId]);

  const currentNode = useMemo(
    () => report?.directory.find((n) => n.id === selectedNodeId) || null,
    [report, selectedNodeId],
  );

  // load paginated records / chapter / device_info for the selected node
  useEffect(() => {
    if (!report || !currentNode) return undefined;
    const needsPaging = currentNode.kind === 'records'
      || currentNode.kind === 'chapter'
      || currentNode.kind === 'device_info';
    if (!needsPaging) {
      setPageData(null);
      return undefined;
    }
    const reqId = ++reqIdRef.current;
    setLoadingPage(true);
    setError(null);
    getIntelligenceRecords(taskId, currentNode.id, page, pageSize)
      .then((data) => { if (reqId === reqIdRef.current) setPageData(data); })
      .catch((err) => { if (reqId === reqIdRef.current) setError(err); })
      .finally(() => { if (reqId === reqIdRef.current) setLoadingPage(false); });
    return () => {};
  }, [report, currentNode, taskId, page, pageSize]);

  const selectNode = useCallback((nodeId) => {
    setSelectedNodeId(nodeId);
    setPage(1);
    setDirOpen(false);
  }, []);

  const runSearch = useCallback((q) => {
    const query = q.trim();
    setSearchSubmitted(query);
    if (!query) { setSearchResult(null); return; }
    setSearching(true);
    searchIntelligenceReport(taskId, query)
      .then((data) => setSearchResult(data))
      .catch(() => setSearchResult({ total: 0, hits: [] }))
      .finally(() => setSearching(false));
  }, [taskId]);

  const clearSearch = useCallback(() => {
    setSearchQuery('');
    setSearchSubmitted('');
    setSearchResult(null);
  }, []);

  if (loadingReport) {
    return <div className="p-8 text-sm text-slate-500">正在加载研判报告…</div>;
  }
  if (error) {
    return (
      <div role="alert" className="m-4 p-4 rounded-xl bg-red-50 text-red-700 text-sm">
        加载研判报告失败：{error?.data?.detail || error?.message || String(error)}
      </div>
    );
  }
  if (!report) return null;

  return (
    <div className="flex flex-col lg:flex-row gap-4 items-start">
      {/* mobile open-directory button */}
      <button
        type="button"
        className="lg:hidden self-start text-xs font-semibold px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
        onClick={() => setDirOpen(true)}
      >
        ☰ 报告目录
      </button>

      {/* left directory */}
      {dirOpen && (
        <button
          type="button"
          aria-label="关闭目录"
          className="fixed inset-0 z-40 bg-slate-950/55 lg:hidden"
          onClick={() => setDirOpen(false)}
        />
      )}
      <aside
        className={`${dirOpen ? 'fixed inset-y-0 left-0 z-50 block w-[min(90vw,20rem)] overflow-y-auto bg-white p-4 shadow-2xl dark:bg-slate-900' : 'hidden'} lg:sticky lg:top-20 lg:block lg:w-72 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:rounded-2xl lg:border lg:border-slate-200 lg:bg-white/70 lg:p-3 lg:shadow-sm dark:lg:border-slate-700 dark:lg:bg-slate-900/70`}
      >
        <ReportReaderSearch
          query={searchQuery}
          onQueryChange={setSearchQuery}
          onSubmit={() => runSearch(searchQuery)}
          onClear={clearSearch}
          searching={searching}
          result={searchResult}
          onHit={(hit) => selectNode(hit.category)}
          submitted={searchSubmitted}
        />
        <ReportReaderDirectory
          directory={report.directory}
          selectedId={selectedNodeId}
          onSelect={selectNode}
        />
        <button
          type="button"
          className="mt-3 w-full text-xs font-semibold px-3 py-2 rounded-lg border border-purple-300 text-purple-700 bg-purple-50 hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-700"
          onClick={() => navigate(`/analysis-center?task_id=${encodeURIComponent(taskId)}`)}
        >
          🛠 研判工具
        </button>
      </aside>

      {/* main content + pagination */}
      <main className="flex-1 min-w-0 space-y-4">
        <header className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">{report.metadata.title}</h1>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span>任务：{report.metadata.task_id}</span>
            {report.metadata.image_path && <span>镜像：{report.metadata.image_path}</span>}
            {report.metadata.generated_at && <span>生成：{report.metadata.generated_at}</span>}
          </div>
        </header>

        <ReportReaderContent
          node={currentNode}
          report={report}
          pageData={pageData}
          loading={loadingPage}
          taskId={taskId}
          metadata={metadata}
          onEditMetadata={() => setEditorOpen(true)}
        />

        {currentNode?.kind === 'records' && pageData && (
          <ReportReaderPagination
            page={pageData.page}
            totalPages={pageData.total_pages}
            onPage={setPage}
          />
        )}
      </main>

      <ReportMetadataEditor
        taskId={taskId}
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={(saved) => setMetadata(saved)}
      />
    </div>
  );
}
