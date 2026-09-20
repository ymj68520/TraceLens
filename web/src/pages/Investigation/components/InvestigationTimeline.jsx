import { useEffect, useMemo, useRef, useState } from 'react';
import { Clock3, FileText, Filter } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Spinner from '../../../components/common/Spinner';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

// review_status → 轴上节点圆点颜色（与 REVIEW_STATUS 徽章语义对齐）
const DOT_COLOR = {
  draft: 'bg-slate-400 dark:bg-slate-500',
  review_pending: 'bg-amber-400',
  confirmed: 'bg-emerald-500',
  rejected: 'bg-rose-500',
};

// 文件节点的圆点取其关联事件评审状态的汇合：
// 有已确认事件 → 绿；有待复核 → 黄；全被排除 → 红；其余 → 草稿灰。
const dotKeyOf = (events) => {
  if (!events.length) return 'draft';
  if (events.some((event) => event.review_status === 'confirmed')) return 'confirmed';
  if (events.some((event) => event.review_status === 'review_pending')) return 'review_pending';
  if (events.every((event) => event.review_status === 'rejected')) return 'rejected';
  return 'draft';
};

const toUnix = (value) => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
};

// 轴体顺序：文件按 MACB 最新时间降序（最新在轴顶），无时间的文件按路径垫底。
const orderFiles = (files) => {
  const dated = [];
  const undated = [];
  files.forEach((file) => {
    const latest = toUnix(file.latest_time);
    (latest === null ? undated : dated).push({ file, latest });
  });
  dated.sort((a, b) => b.latest - a.latest || String(a.file.path).localeCompare(String(b.file.path)));
  undated.sort((a, b) => String(a.file.path).localeCompare(String(b.file.path)));
  return [...dated.map((entry) => entry.file), ...undated.map((entry) => entry.file)];
};

// 轴体两端的时间范围：文件 MACB 最新时间的最小/最大值。
const axisBounds = (files) => {
  let start = null;
  let end = null;
  files.forEach((file) => {
    const latest = toUnix(file.latest_time);
    if (latest === null) return;
    if (start === null || latest < start) start = latest;
    if (end === null || latest > end) end = latest;
  });
  return { start, end };
};

// 节点展示时间：文件 MACB 最新时间；不可解析统一显示 时间未知。
const displayTime = (file) => {
  const latest = toUnix(file.latest_time);
  return latest === null ? '时间未知' : formatTimestamp(latest);
};

// MACB 四类时间戳（创建/修改/访问/变更），只显示可解析项。
const MACB_ROWS = [
  { key: 'crtime', label: '创建' },
  { key: 'mtime', label: '修改' },
  { key: 'atime', label: '访问' },
  { key: 'ctime', label: '变更' },
];

const formatSize = (size) => {
  const n = Number(size);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
};

// 时间过滤：datetime-local 本地时间串 → unix 秒；空串/非法输入返回 null（不设界）。
const fromDatetimeLocalValue = (value) => {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : Math.floor(time / 1000);
};

export default function InvestigationTimeline({ files, events, selectedFileKey, onSelectFile, onSelectEvent, loading }) {
  const [expandedKey, setExpandedKey] = useState(null);
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');
  const nodeRefs = useRef({});

  const eventsById = useMemo(() => {
    const map = new Map();
    (events || []).forEach((event) => map.set(event.id, event));
    return map;
  }, [events]);

  // 文件 → 佐证事件视图（按事件时间升序，无时间的按 id 垫底）。
  const resolveEvents = (file) => {
    const ids = file.event_ids || [];
    const resolved = ids.map((id) => eventsById.get(id)).filter(Boolean);
    return resolved.sort((a, b) => (toUnix(a.start_time) ?? Infinity) - (toUnix(b.start_time) ?? Infinity));
  };

  const ordered = useMemo(() => orderFiles(files || []), [files]);

  // 时间过滤：文件 MACB 最新时间（即节点在轴上的位置）落在区间内才命中；
  // 无时间的文件无法匹配，过滤时隐藏。
  const filterStartUnix = fromDatetimeLocalValue(filterStart);
  const filterEndUnix = fromDatetimeLocalValue(filterEnd);
  const filterActive = filterStartUnix !== null || filterEndUnix !== null;
  const visible = useMemo(() => {
    if (!filterActive) return ordered;
    return ordered.filter((file) => {
      const latest = toUnix(file.latest_time);
      if (latest === null) return false;
      if (filterStartUnix !== null && latest < filterStartUnix) return false;
      if (filterEndUnix !== null && latest > filterEndUnix) return false;
      return true;
    });
  }, [ordered, filterActive, filterStartUnix, filterEndUnix]);

  // 轴体两端的时间帽跟随过滤结果收敛。
  const axis = useMemo(() => axisBounds(visible), [visible]);

  // 外部选择（URL、图谱联动）滚动定位；卡片只靠点击展开。
  useEffect(() => {
    if (!selectedFileKey) return;
    nodeRefs.current[selectedFileKey]?.scrollIntoView?.({ block: 'nearest' });
  }, [selectedFileKey, visible]);

  if (loading) return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  if (!files.length) {
    return <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">暂无已分析文件。请确认初次流水线已完成并产生已分析 Event Cluster。</div>;
  }

  const toggle = (file) => {
    setExpandedKey((current) => (current === file.path ? null : file.path));
    onSelectFile(file);
  };

  const clearFilter = () => {
    setFilterStart('');
    setFilterEnd('');
  };

  return (
    <div className="h-full overflow-y-auto px-3 py-4" data-testid="investigation-timeline">
      {/* 时间过滤栏（吸顶） */}
      <div
        className="sticky -top-4 z-20 -mx-3 mb-3 flex flex-wrap items-center gap-1.5 border-b border-slate-100 bg-white/90 px-3 py-2 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90"
        data-testid="timeline-filter"
      >
        <Filter size={12} className="shrink-0 text-slate-400" />
        <input
          type="datetime-local"
          step="1"
          aria-label="起始时间"
          data-testid="timeline-filter-start"
          value={filterStart}
          onChange={(e) => setFilterStart(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        />
        <span className="text-[11px] text-slate-400">→</span>
        <input
          type="datetime-local"
          step="1"
          aria-label="结束时间"
          data-testid="timeline-filter-end"
          value={filterEnd}
          onChange={(e) => setFilterEnd(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        />
        {filterActive && (
          <>
            <span className="text-[11px] text-slate-400" data-testid="timeline-filter-count">
              {visible.length}/{files.length}
            </span>
            <button
              type="button"
              onClick={clearFilter}
              data-testid="timeline-filter-clear"
              className="rounded-lg border border-slate-200 px-1.5 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
            >
              清除
            </button>
          </>
        )}
      </div>

      {visible.length === 0 ? (
        <div
          className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400"
          data-testid="timeline-filter-empty"
        >
          该时间范围内没有已分析文件，请调整或清除过滤条件。
        </div>
      ) : (
      <div className="relative" data-testid="timeline-axis">
        <span aria-hidden className="absolute bottom-4 left-1/2 top-4 w-px -translate-x-1/2 bg-slate-300 dark:bg-slate-600" />

        {/* 轴体顶端：最早文件时间 */}
        <div className="relative mb-4 flex items-center gap-2" data-testid="timeline-axis-start">
          <span aria-hidden className="h-px flex-1 bg-gradient-to-r from-transparent to-slate-300 dark:to-slate-600" />
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Clock3 size={11} className="text-primary-500" />
            {formatTimestamp(axis.start)}
          </span>
          <span aria-hidden className="h-px flex-1 bg-gradient-to-l from-transparent to-slate-300 dark:to-slate-600" />
        </div>

        {visible.map((file, index) => {
          const fileEvents = resolveEvents(file);
          const status = REVIEW_STATUS[dotKeyOf(fileEvents)];
          const selected = selectedFileKey === file.path;
          const expanded = expandedKey === file.path;
          const sideIsLeft = index % 2 === 0;
          const toggleThis = () => toggle(file);
          const sizeLabel = formatSize(file.size);

          const chip = (
            <button
              type="button"
              onClick={toggleThis}
              title={file.path}
              data-testid={`file-chip-${file.path}`}
              className={`max-w-full rounded-lg border px-2 py-1 transition-colors ${sideIsLeft ? 'text-right' : 'text-left'} ${selected
                ? 'border-primary-300 bg-primary-50/60 dark:border-primary-700 dark:bg-primary-950/30'
                : 'border-transparent hover:border-slate-200 hover:bg-slate-100/70 dark:hover:border-slate-700 dark:hover:bg-slate-800/60'}`}
            >
              <span className={`block text-[10px] leading-3 text-slate-400`}>
                <Clock3 className="mr-0.5 inline h-2.5 w-2.5" />
                {displayTime(file)}
              </span>
              <span className="mt-0.5 block truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                {file.name || file.path}
              </span>
            </button>
          );

          return (
            <div
              key={file.path}
              ref={(el) => { nodeRefs.current[file.path] = el; }}
              data-side={sideIsLeft ? 'left' : 'right'}
              data-testid={`file-${file.path}`}
            >
              {/* minmax(0,1fr)：裸 1fr 的下限是 min-content，会被不可断行的长文件名撑爆轴体 */}
              <div className="grid grid-cols-[minmax(0,1fr)_2.5rem_minmax(0,1fr)] items-center py-1.5">
                <div className={sideIsLeft ? 'flex justify-end' : ''}>
                  {!expanded && sideIsLeft && chip}
                </div>
                <div className="relative z-10 flex justify-center">
                  <button
                    type="button"
                    onClick={toggleThis}
                    aria-expanded={expanded}
                    aria-current={selected ? 'true' : undefined}
                    aria-label={`${displayTime(file)} ${file.name || file.path}`}
                    title={`${status.label} · ${displayTime(file)}`}
                    data-testid={`file-node-${file.path}`}
                    className={`h-3.5 w-3.5 cursor-pointer rounded-full border-2 shadow transition-all hover:scale-125 border-white dark:border-slate-900 ${DOT_COLOR[dotKeyOf(fileEvents)]} ${expanded
                      ? 'ring-2 ring-primary-500 ring-offset-2 ring-offset-white dark:ring-offset-slate-900'
                      : selected ? 'ring-2 ring-primary-300 dark:ring-primary-600' : ''}`}
                  />
                </div>
                <div className={!sideIsLeft ? 'flex justify-start' : ''}>
                  {!expanded && !sideIsLeft && chip}
                </div>
              </div>
              {expanded && (
                <div
                  className="relative mb-3 mt-1.5 rounded-xl border border-primary-300 bg-white p-3 shadow-md dark:border-primary-700/60 dark:bg-slate-900"
                  data-testid={`file-card-${file.path}`}
                >
                  <span aria-hidden className="absolute -top-1.5 left-1/2 h-1.5 w-px -translate-x-1/2 bg-slate-300 dark:bg-slate-600" />
                  {/* 文件为核心：身份 → MACB 时间 → 自身摘要 → 事件佐证 */}
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                      <FileText size={14} className="shrink-0 text-primary-500" />
                      <span className="truncate">{file.name || file.path}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                      <Clock3 size={12} /> {displayTime(file)}
                    </span>
                  </div>
                  <div className="mt-1 break-all font-mono text-[11px] text-slate-400">{file.path}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                    {sizeLabel && <span>{sizeLabel}</span>}
                    {file.category && <span>{file.category}</span>}
                    {file.extension && <span>{file.extension}</span>}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                    {MACB_ROWS.map(({ key, label }) => {
                      const value = toUnix(file[key]);
                      return (
                        <span key={key} className={value === null ? 'text-slate-400' : `${'text-slate-600 dark:text-slate-300'}`}>
                          {label} {formatTimestamp(value)}
                        </span>
                      );
                    })}
                  </div>
                  {file.llm_summary && (
                    <p className="mt-2 whitespace-pre-wrap break-words text-xs text-slate-600 dark:text-slate-400">{file.llm_summary}</p>
                  )}
                  <div className="mt-2 border-t border-slate-100 pt-2 dark:border-slate-800">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">佐证事件 · {fileEvents.length}</div>
                    {fileEvents.length ? (
                      <div className="mt-1.5 space-y-1">
                        {fileEvents.map((event) => {
                          const eventStatus = REVIEW_STATUS[event.review_status] || REVIEW_STATUS.draft;
                          return (
                            <button
                              key={event.id}
                              type="button"
                              onClick={() => onSelectEvent?.(event.id)}
                              data-testid={`file-card-event-${event.id}`}
                              className="flex w-full items-center gap-2 rounded-lg border border-transparent px-1.5 py-1 text-left text-xs transition-colors hover:border-slate-200 hover:bg-slate-100/70 dark:hover:border-slate-700 dark:hover:bg-slate-800/60"
                            >
                              <span className={`h-2 w-2 shrink-0 rounded-full ${DOT_COLOR[dotKeyOf([event])]}`} />
                              <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">{event.title}</span>
                              <span className="shrink-0 text-[10px] text-slate-400">{formatTimestamp(toUnix(event.start_time))}</span>
                              <Badge variant={eventStatus.variant} size="sm">{eventStatus.label}</Badge>
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-1 text-[11px] text-slate-400">暂无关联事件</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* 轴体底端：最晚文件时间 */}
        <div className="relative mt-4 flex items-center gap-2" data-testid="timeline-axis-end">
          <span aria-hidden className="h-px flex-1 bg-gradient-to-r from-transparent to-slate-300 dark:to-slate-600" />
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Clock3 size={11} className="text-primary-500" />
            {formatTimestamp(axis.end)}
          </span>
          <span aria-hidden className="h-px flex-1 bg-gradient-to-l from-transparent to-slate-300 dark:to-slate-600" />
        </div>
      </div>
      )}
    </div>
  );
}
