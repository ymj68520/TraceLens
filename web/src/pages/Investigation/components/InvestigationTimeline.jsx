import { useEffect, useMemo, useRef, useState } from 'react';
import { Clock3, Database, FileCheck2, Filter } from 'lucide-react';
import Badge from '../../../components/common/Badge';
import Spinner from '../../../components/common/Spinner';
import { REVIEW_STATUS, formatTimestamp } from '../utils/investigationConstants';

const count = (event, key) => event.evidence_counts?.[key] || 0;

// review_status → 轴上节点圆点颜色（与 REVIEW_STATUS 徽章语义对齐）
const DOT_COLOR = {
  draft: 'bg-slate-400 dark:bg-slate-500',
  review_pending: 'bg-amber-400',
  confirmed: 'bg-emerald-500',
  rejected: 'bg-rose-500',
};

const toUnix = (value) => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
};

// 轴体顺序：有时间的按 start_time 升序（最早在轴顶），无时间的事件按原顺序垫底。
const orderEvents = (events) => {
  const dated = [];
  const undated = [];
  events.forEach((event) => {
    const start = toUnix(event.start_time);
    (start === null ? undated : dated).push({ event, start });
  });
  dated.sort((a, b) => a.start - b.start);
  return [...dated.map((entry) => entry.event), ...undated.map((entry) => entry.event)];
};

// 轴体两端的证据时间范围：最早 start_time 到最晚 end_time（缺 end 用 start 兜底）。
const axisBounds = (events) => {
  let start = null;
  let end = null;
  events.forEach((event) => {
    const s = toUnix(event.start_time);
    if (s === null) return;
    if (start === null || s < start) start = s;
    const e = toUnix(event.end_time) || s;
    if (end === null || e > end) end = e;
  });
  return { start, end };
};

const statusKeyOf = (event) => (REVIEW_STATUS[event.review_status] ? event.review_status : 'draft');

// 节点展示时间：不可解析的时间戳（缺失/脏数据）统一显示 时间未知。
const displayTime = (event) => {
  const start = toUnix(event.start_time);
  return start === null ? '时间未知' : formatTimestamp(start);
};

// 时间过滤：datetime-local 本地时间串 → unix 秒；空串/非法输入返回 null（不设界）。
const fromDatetimeLocalValue = (value) => {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : Math.floor(time / 1000);
};

export default function InvestigationTimeline({ events, selectedEventId, onSelect, loading }) {
  const [expandedId, setExpandedId] = useState(null);
  const [filterStart, setFilterStart] = useState('');
  const [filterEnd, setFilterEnd] = useState('');
  const nodeRefs = useRef({});

  const ordered = useMemo(() => orderEvents(events), [events]);

  // 时间过滤：事件发生时间（start_time，即节点在轴上的位置）落在区间内才命中；
  // 无时间的事件无法匹配，过滤时隐藏。
  const filterStartUnix = fromDatetimeLocalValue(filterStart);
  const filterEndUnix = fromDatetimeLocalValue(filterEnd);
  const filterActive = filterStartUnix !== null || filterEndUnix !== null;
  const visible = useMemo(() => {
    if (!filterActive) return ordered;
    return ordered.filter((event) => {
      const start = toUnix(event.start_time);
      if (start === null) return false;
      if (filterStartUnix !== null && start < filterStartUnix) return false;
      if (filterEndUnix !== null && start > filterEndUnix) return false;
      return true;
    });
  }, [ordered, filterActive, filterStartUnix, filterEndUnix]);

  // 轴体两端的时间帽跟随过滤结果收敛。
  const axis = useMemo(() => axisBounds(visible), [visible]);

  // 外部选择（URL ?event=、图谱节点点击）滚动定位；卡片只靠点击展开。
  useEffect(() => {
    if (!selectedEventId) return;
    nodeRefs.current[selectedEventId]?.scrollIntoView?.({ block: 'nearest' });
  }, [selectedEventId, visible]);

  if (loading) return <div className="h-full flex items-center justify-center"><Spinner /></div>;
  if (!events.length) {
    return <div className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">暂无调查事件。请确认初次流水线已完成并产生已分析 Event Cluster。</div>;
  }

  const toggle = (event) => {
    setExpandedId((current) => (current === event.id ? null : event.id));
    onSelect(event.id);
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
              {visible.length}/{events.length}
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
          该时间范围内没有事件，请调整或清除过滤条件。
        </div>
      ) : (
      <div className="relative" data-testid="timeline-axis">
        <span aria-hidden className="absolute bottom-4 left-1/2 top-4 w-px -translate-x-1/2 bg-slate-300 dark:bg-slate-600" />

        {/* 轴体顶端：证据最早时间 */}
        <div className="relative mb-4 flex items-center gap-2" data-testid="timeline-axis-start">
          <span aria-hidden className="h-px flex-1 bg-gradient-to-r from-transparent to-slate-300 dark:to-slate-600" />
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Clock3 size={11} className="text-primary-500" />
            {formatTimestamp(axis.start)}
          </span>
          <span aria-hidden className="h-px flex-1 bg-gradient-to-l from-transparent to-slate-300 dark:to-slate-600" />
        </div>

        {visible.map((event, index) => {
          const status = REVIEW_STATUS[statusKeyOf(event)];
          const selected = selectedEventId === event.id;
          const expanded = expandedId === event.id;
          const sideIsLeft = index % 2 === 0;
          const toggleThis = () => toggle(event);

          const chip = (
            <button
              type="button"
              onClick={toggleThis}
              title={event.title || '(未命名事件)'}
              data-testid={`event-chip-${event.id}`}
              className={`max-w-full rounded-lg border px-2 py-1 transition-colors ${sideIsLeft ? 'text-right' : 'text-left'} ${selected
                ? 'border-primary-300 bg-primary-50/60 dark:border-primary-700 dark:bg-primary-950/30'
                : 'border-transparent hover:border-slate-200 hover:bg-slate-100/70 dark:hover:border-slate-700 dark:hover:bg-slate-800/60'}`}
            >
              <span className={`block text-[10px] leading-3 text-slate-400`}>
                <Clock3 className="mr-0.5 inline h-2.5 w-2.5" />
                {displayTime(event)}
              </span>
              <span className="mt-0.5 block truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                {event.title || '(未命名事件)'}
              </span>
            </button>
          );

          return (
            <div
              key={event.id}
              ref={(el) => { nodeRefs.current[event.id] = el; }}
              data-side={sideIsLeft ? 'left' : 'right'}
              data-testid={`event-${event.id}`}
            >
              {/* minmax(0,1fr)：裸 1fr 的下限是 min-content，会被不可断行的长标题撑爆轴体 */}
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
                    aria-label={`${displayTime(event)} ${event.title || ''}`}
                    title={`${status.label} · ${displayTime(event)}`}
                    data-testid={`event-node-${event.id}`}
                    className={`h-3.5 w-3.5 cursor-pointer rounded-full border-2 shadow transition-all hover:scale-125 border-white dark:border-slate-900 ${DOT_COLOR[statusKeyOf(event)]} ${expanded
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
                  data-testid={`event-card-${event.id}`}
                >
                  <span aria-hidden className="absolute -top-1.5 left-1/2 h-1.5 w-px -translate-x-1/2 bg-slate-300 dark:bg-slate-600" />
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant={status.variant} size="sm">{status.label}</Badge>
                    <span className="flex items-center gap-1 text-xs text-slate-500">
                      <Clock3 size={12} /> {displayTime(event)}
                    </span>
                  </div>
                  <h3 className="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">{event.title}</h3>
                  {event.summary && (
                    <p className="mt-1 whitespace-pre-wrap break-words text-xs text-slate-600 dark:text-slate-400">{event.summary}</p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                    <span className="inline-flex items-center gap-1"><Database size={12} />Primary {count(event, 'primary')}</span>
                    <span>Supporting {count(event, 'supporting')}</span>
                    <span>Contradicting {count(event, 'contradicting')}</span>
                    <span className="inline-flex items-center gap-1"><FileCheck2 size={12} />Report {event.report_evidence_count || 0}</span>
                  </div>
                  <div className="mt-1.5 text-[11px] uppercase tracking-wide text-slate-400">{event.source === 'cluster_seed' ? 'Cluster Seed' : event.source}</div>
                </div>
              )}
            </div>
          );
        })}

        {/* 轴体底端：证据最晚时间 */}
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
