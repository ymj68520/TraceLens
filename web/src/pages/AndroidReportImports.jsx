import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { FileArchive, FileSearch, ShieldAlert, Download, Search } from 'lucide-react';

import Card from '../components/common/Card';
import Button from '../components/common/Button';
import { FIELD_AUTH_ENABLED } from '../config/runtime';
import { openFieldResource } from '../services/fieldResource';
import {
  androidReportAttachmentUrl,
  androidReportSourceUrl,
  androidReportSourceLocationUrl,
  attachAndroidReportToTask,
  createAndroidReportImportFromCandidate,
  detachAndroidReportFromTask,
  getAndroidReportOverview,
  getAndroidReportRecord,
  getAndroidReportRecords,
  listAndroidReportCandidates,
  listAndroidReportImports,
} from '../services/androidReportService';

const errorText = (error) => error?.data?.detail || error?.message || '请求失败';
const statusLabel = { COMPLETE: '完整', PARTIAL: '部分导入', FAILED: '失败' };

export default function AndroidReportImports() {
  const [params, setParams] = useSearchParams();
  const importId = params.get('import_id');
  const taskId = params.get('task_id');
  const [candidates, setCandidates] = useState([]);
  const [candidateId, setCandidateId] = useState('');
  const [imports, setImports] = useState([]);
  const [overview, setOverview] = useState(null);
  const [result, setResult] = useState(null);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [importing, setImporting] = useState(false);
  const [linkingId, setLinkingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');
  const detailRequest = useRef(0);
  const openProtected = (event, url, options) => {
    if (!FIELD_AUTH_ENABLED) return;
    event.preventDefault();
    openFieldResource(url, options).catch((err) => setError(err.message));
  };

  useEffect(() => {
    let active = true;
    Promise.all([listAndroidReportImports(), listAndroidReportCandidates()]).then(([stored, found]) => {
      if (!active) return;
      setImports(stored.imports || []);
      setCandidates(found.candidates || []);
      setCandidateId((current) => current || found.candidates?.[0]?.id || '');
    }).catch((err) => {
      if (active) setError(errorText(err));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!taskId || importId) return;
    const linked = imports.find((item) => item.task_ids?.includes(taskId));
    if (!linked) return;
    const next = new URLSearchParams(params);
    next.set('import_id', linked.import_id);
    setParams(next, { replace: true });
  }, [taskId, importId, imports, params, setParams]);

  useEffect(() => {
    detailRequest.current += 1;
    if (!importId) { setOverview(null); setResult(null); setSelectedRecord(null); return undefined; }
    let active = true;
    setOverview(null);
    setResult(null);
    setSelectedRecord(null);
    setDetailLoading(false);
    setError('');
    getAndroidReportOverview(importId).then((data) => {
      if (active) setOverview(data.overview);
    }).catch((err) => {
      if (active) setError(errorText(err));
    });
    return () => { active = false; };
  }, [importId]);

  useEffect(() => {
    if (!importId) return undefined;
    let active = true;
    setLoading(true);
    getAndroidReportRecords(importId, { query, category, page, page_size: 50 }).then((data) => {
      if (active) setResult(data);
    }).catch((err) => {
      if (active) setError(errorText(err));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [importId, query, category, page]);

  const selectImport = (id) => {
    const next = new URLSearchParams(params);
    next.set('mode', 'report');
    next.set('import_id', id);
    setParams(next);
    setPage(1);
    setCategory('');
    setQuery('');
    setQueryInput('');
  };

  const submitImport = async (event) => {
    event.preventDefault();
    if (!candidateId) return;
    setImporting(true);
    setError('');
    try {
      const data = await createAndroidReportImportFromCandidate(candidateId);
      setImports((items) => [data.import, ...items.filter((item) => item.import_id !== data.import.import_id)]);
      setCandidates((items) => items.map((item) => item.id === candidateId
        ? { ...item, existing_import_id: data.import.import_id } : item));
      const meta = taskId
        ? (await attachAndroidReportToTask(data.import.import_id, taskId)).import
        : data.import;
      setImports((items) => [meta, ...items.filter((item) => item.import_id !== meta.import_id)]);
      selectImport(meta.import_id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setImporting(false);
    }
  };

  const toggleTaskLink = async (item, checked) => {
    if (!taskId) return;
    setLinkingId(item.import_id);
    setError('');
    try {
      const response = checked
        ? await attachAndroidReportToTask(item.import_id, taskId)
        : await detachAndroidReportFromTask(item.import_id, taskId);
      setImports((items) => items.map((current) => current.import_id === item.import_id
        ? response.import : current));
      if (overview?.import?.import_id === item.import_id) {
        setOverview((current) => ({ ...current, import: response.import }));
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLinkingId(null);
    }
  };

  const openRecord = async (id) => {
    const request = ++detailRequest.current;
    setDetailLoading(true);
    setSelectedRecord(null);
    setError('');
    try {
      const data = await getAndroidReportRecord(importId, id);
      if (request === detailRequest.current) setSelectedRecord(data.record);
    } catch (err) {
      if (request === detailRequest.current) setError(errorText(err));
    } finally {
      if (request === detailRequest.current) setDetailLoading(false);
    }
  };

  const meta = overview?.import;
  const pageCount = Math.max(1, Math.ceil((result?.total || 0) / 50));

  return <div className="space-y-5" data-testid="android-report-imports">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white">安卓离线报告分析</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">导入已有取证工具导出的报告包；检索、分类、时间统计和来源追溯。</p>
      </div>
      {taskId && <Link to={`/android?task_id=${encodeURIComponent(taskId)}`} className="text-sm font-semibold text-primary-600 hover:underline">返回 MIUI 备份分析</Link>}
    </div>

    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-200">
      <div className="flex gap-2"><ShieldAlert className="h-5 w-5 shrink-0" /><p>这里展示的是第三方报告中的派生记录，不是手机原始镜像或应用数据库。报告的脚本和可执行文件不会运行；日期保留报告原值，未擅自换算时区。</p></div>
    </div>

    <Card title="选择离线报告" subtitle="系统从服务器证据目录发现报告包；不需要填写文件路径，原目录只读。">
      <form onSubmit={submitImport} className="flex flex-col gap-3 sm:flex-row">
        <label className="min-w-0 flex-1 text-xs font-semibold text-slate-600 dark:text-slate-300">已发现的报告
          <select aria-label="已发现的报告" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white">
            {!candidates.length && <option value="">未发现可导入的报告</option>}
            {candidates.map((item) => <option key={item.id} value={item.id}>{item.name}{item.existing_import_id ? ' · 已索引' : ''}</option>)}
          </select>
        </label>
        <Button type="submit" loading={importing} disabled={!candidateId} icon={FileArchive} className="self-end">{taskId ? '导入并关联当前 Task' : '导入并建立索引'}</Button>
      </form>
      <p className="mt-2 text-xs text-slate-500">默认查找项目上级目录中的报告包；可用 ANDROID_REPORT_SEARCH_ROOT 配置证据目录。只索引导出文字与附件引用，不执行厂商程序。</p>
      {taskId && <p className="mt-1 text-xs text-amber-700">当前 Task：{taskId}。关联只表示人工选择，未核验报告与 Task 是否来自同一检材。</p>}
    </Card>

    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}

    <Card title={`已导入报告 · ${imports.length}`}>
      {!imports.length ? <p className="text-sm text-slate-500">暂无导入记录。</p> : <div className="flex flex-wrap gap-2">
        {imports.map((item) => <div key={item.import_id} className={`max-w-full rounded-xl border px-3 py-2 text-sm ${importId === item.import_id ? 'border-primary-500 bg-primary-50 text-primary-800' : 'border-slate-200 bg-white'}`}>
          <button type="button" onClick={() => selectImport(item.import_id)} className="block max-w-sm text-left hover:underline">
            <span className="block max-w-sm truncate font-semibold" title={item.source_path}>{item.specimens?.[0]?.specimen || item.source_path}</span>
            <span className="text-xs text-slate-500">{item.record_count?.toLocaleString() ?? 0} 条索引记录 · {item.page_count} 页 · {statusLabel[item.status] || '未评估'}</span>
          </button>
          {taskId && <label className="mt-2 flex items-center gap-2 border-t border-slate-200 pt-2 text-xs font-medium">
            <input type="checkbox" checked={Boolean(item.task_ids?.includes(taskId))} disabled={linkingId === item.import_id} onChange={(event) => toggleTaskLink(item, event.target.checked)} />关联当前 Task
          </label>}
        </div>)}
      </div>}
    </Card>

    {meta && <>
      <Card title="报告分析概览" subtitle="统计来自导出报告的表格行，不代表原始手机数据总量。">
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">已索引记录</p><p className="text-2xl font-bold">{meta.record_count?.toLocaleString()}</p></div>
          <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">报告内容页</p><p className="text-2xl font-bold">{meta.page_count}</p></div>
          <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">缺失附件引用</p><p className="text-2xl font-bold">{meta.missing_attachment_count}</p></div>
          <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">导入状态 / 完整度</p><p className="text-lg font-bold">{statusLabel[meta.status] || '未评估'}</p><p className="text-xs text-slate-500">{overview.coverage ? `${overview.coverage.successful_pages} / ${overview.coverage.declared_pages || overview.coverage.total_pages} 页 · ${overview.coverage.warning_count} 条 warning` : '旧索引需重新导入'}</p></div>
        </div>
        {!!overview.warnings?.length && <details className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><summary className="cursor-pointer font-semibold">导入 warning · {overview.warnings.length}</summary><ul className="mt-2 space-y-1">{overview.warnings.slice(0, 100).map((item, index) => <li key={`${item.code}-${item.path || ''}-${index}`} className="break-all">{item.code}{item.path ? ` · ${item.path}` : ''}{item.detail ? ` · ${item.detail}` : ''}</li>)}</ul>{overview.warnings.length > 100 && <p>仅显示前 100 条；完整列表见 report_manifest.json。</p>}</details>}
        {!!meta.unhashed_attachment_count && <p className="mt-2 text-xs text-amber-700">{meta.unhashed_attachment_count} 个附件因大小或导入哈希预算限制未计算指纹，下载前无法做完整性比对。</p>}
        {!!meta.missing_attachment_paths?.length && <details className="mt-2 text-xs text-rose-700"><summary className="cursor-pointer font-semibold">查看缺失附件路径（最多 100 项）</summary><ul className="mt-2 space-y-1">{meta.missing_attachment_paths.map((path) => <li key={path} className="break-all font-mono">{path}</li>)}</ul></details>}
        <p className="mt-3 break-all text-xs text-slate-500">来源目录：{meta.source_path}</p>
        <p className="mt-1 text-xs text-slate-500">生成软件：{meta.specimens?.[0]?.software || '未记录'} · {meta.specimens?.[0]?.version || '版本未知'}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {overview.categories.map((item) => <button key={item.category} type="button" onClick={() => { setCategory(item.category === category ? '' : item.category); setPage(1); }} className={`rounded-full border px-3 py-1 text-xs ${category === item.category ? 'border-primary-500 bg-primary-50 font-bold text-primary-700' : 'border-slate-200 text-slate-600 hover:border-primary-300'}`}>{item.category} {item.count.toLocaleString()}</button>)}
        </div>
        {!!overview.days?.length && <div className="mt-4"><h3 className="text-sm font-semibold">报告记录中的日期分布（最近 10 日）</h3><div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-5">{overview.days.slice(-10).map((item) => <div key={item.day} className="rounded-lg bg-slate-50 px-2 py-1 text-xs">{item.day} · {item.count}</div>)}</div></div>}
      </Card>

      <Card title="检索报告记录" subtitle="按导出页面顺序浏览；搜索只匹配已索引的可见文字。">
        <form onSubmit={(event) => { event.preventDefault(); setQuery(queryInput.trim()); setPage(1); }} className="mb-3 flex flex-wrap gap-2">
          <input aria-label="搜索报告记录" value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder="关键词、号码或文件名" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          <Button type="submit" size="sm" icon={Search}>搜索</Button>
          {(category || query) && <Button size="sm" variant="ghost" onClick={() => { setCategory(''); setQuery(''); setQueryInput(''); setPage(1); }}>清除筛选</Button>}
        </form>
        {loading ? <p role="status" className="text-sm text-slate-500">正在检索…</p> : <p className="mb-2 text-xs text-slate-500">共 {result?.total?.toLocaleString() ?? 0} 条 · 第 {page} / {pageCount} 页</p>}
        <div className="max-h-[55vh] space-y-2 overflow-y-auto">
          {(result?.records || []).map((item) => <button key={item.id} type="button" onClick={() => openRecord(item.id)} className="block w-full rounded-xl border border-slate-200 p-3 text-left hover:border-primary-400 hover:bg-primary-50/40" data-testid="android-report-record">
            <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded bg-indigo-50 px-2 py-0.5 font-semibold text-indigo-700">{item.category}</span><span className="font-semibold text-slate-700">{item.heading}</span>{item.record_kind === 'section_text' && <span className="text-amber-700">文本章节</span>}{item.occurred_at && <span className="text-slate-500">{item.occurred_at}</span>}</div>
            <p className="mt-1 line-clamp-2 break-all text-sm text-slate-700">{item.excerpt}</p>
            <p className="mt-1 truncate font-mono text-[11px] text-slate-400" title={item.source_file}>{item.source_file} · {item.record_kind === 'section_text' ? `章节 ${item.source_row}` : `表 ${item.source_table} / 行 ${item.source_row}`}</p>
          </button>)}
        </div>
        <div className="mt-3 flex justify-end gap-2"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>下一页</Button></div>
      </Card>

      {(detailLoading || selectedRecord) && <Card title="记录来源与详情">
        {detailLoading ? <p role="status">正在读取记录…</p> : <div className="space-y-4" data-testid="android-report-detail">
          <div className="flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-amber-100 px-2 py-1 font-semibold text-amber-800">第三方报告派生记录</span><span className="text-slate-500">{selectedRecord.specimen} · {selectedRecord.category}</span></div>
          <div className="rounded-xl bg-slate-50 p-3"><p className="whitespace-pre-wrap break-all text-sm text-slate-800">{selectedRecord.content || selectedRecord.raw_text}</p>{selectedRecord.content_truncated && <p className="mt-2 text-xs text-amber-700">该行过长，索引正文已截断；可下载对应报告页核对。</p>}</div>
          {!!Object.keys(selectedRecord.raw_fields || selectedRecord.fields || {}).length && <dl className="grid gap-2 sm:grid-cols-2">{Object.entries(selectedRecord.raw_fields || selectedRecord.fields).map(([key, value]) => <div key={key} className="min-w-0 rounded-lg border border-slate-200 p-2 text-xs"><dt className="font-semibold text-slate-500">{key}</dt><dd className="mt-1 break-all">{value}</dd></div>)}</dl>}
          <div className="border-t border-slate-200 pt-3 text-xs"><p className="font-semibold">来源定位</p><p className="mt-1 break-all font-mono">{selectedRecord.source_file} · 页 {selectedRecord.source_page ?? '未编号首页'} / {selectedRecord.record_kind === 'section_text' ? `文本章节 ${selectedRecord.source_row_index ?? selectedRecord.source_row}` : `表 ${selectedRecord.source_table_index ?? selectedRecord.source_table} / 行 ${selectedRecord.source_row_index ?? selectedRecord.source_row}`}</p><p className="mt-1 break-all font-mono">{selectedRecord.source_locator || `${selectedRecord.source_file}#${selectedRecord.source_anchor || '无锚点'}`}</p><p className="mt-1 break-all font-mono text-slate-500">导入时页面 SHA-256：{selectedRecord.source_hash || selectedRecord.source_sha256}</p>
            {selectedRecord.source_matches_import && selectedRecord.source_locator && <a href={androidReportSourceLocationUrl(importId, selectedRecord.id)} target="_blank" rel="noopener noreferrer" onClick={(event) => openProtected(event, androidReportSourceLocationUrl(importId, selectedRecord.id), { newTab: true })} className="mt-2 inline-flex items-center gap-1 font-semibold text-primary-600 hover:underline"><FileSearch className="h-3.5 w-3.5" />查看原始报告位置（安全文本视图）</a>}
            {selectedRecord.source_matches_import ? <a href={androidReportSourceUrl(importId, selectedRecord.source_file)} onClick={(event) => openProtected(event, androidReportSourceUrl(importId, selectedRecord.source_file), { downloadName: 'source-page.txt' })} className="mt-2 inline-flex items-center gap-1 font-semibold text-primary-600 hover:underline"><FileSearch className="h-3.5 w-3.5" />下载原报告页（纯文本，不执行脚本）</a> : <p className="mt-2 font-semibold text-rose-700">原报告页已变更或不可访问，不能按导入时状态回查。</p>}
          </div>
          {!!selectedRecord.attachments?.length && <div><p className="text-xs font-semibold">附件引用</p><div className="mt-2 space-y-2">{selectedRecord.attachments.map((item) => <div key={item.path} className="break-all text-xs"><div className="flex flex-wrap items-center gap-2"><span>{item.path}</span>{item.available ? <a href={androidReportAttachmentUrl(importId, item.path)} onClick={(event) => openProtected(event, androidReportAttachmentUrl(importId, item.path), { downloadName: item.path.split('/').pop() })} className="inline-flex items-center gap-1 font-semibold text-primary-600 hover:underline"><Download className="h-3.5 w-3.5" />下载副本</a> : <span className="text-rose-700">原报告中缺失</span>}</div>{item.sha256 && <p className="mt-0.5 font-mono text-slate-500">导入时附件 SHA-256：{item.sha256}</p>}{item.available && !item.sha256 && <p className="mt-0.5 text-amber-700">导入时未计算哈希，无法做完整性比对。</p>}</div>)}</div></div>}
          <Button variant="ghost" size="sm" onClick={() => setSelectedRecord(null)}>关闭详情</Button>
        </div>}
      </Card>}
    </>}
  </div>;
}
