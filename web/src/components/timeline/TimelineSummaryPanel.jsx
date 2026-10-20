import { useEffect, useRef, useState } from 'react';
import { Clock, RefreshCw, X } from 'lucide-react';
import { getTimelineSummary, getTimelineSummaryRecords } from '../../services/timelineSummaryService';

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const DIRECTIONS = { sent: '发出', received: '收到', unknown: '方向未知', system: '系统消息' };
const BASIS = { recorded: '来源记录时间', file_metadata: '文件时间戳', message: '消息时间',
  inferred: '推定时间（不参与分布）', processing: '采集处理时间（不参与分布）' };
const field = 'rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100';
const button = 'rounded-lg border border-blue-200 px-3 py-2 text-sm text-blue-800 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-800 dark:text-blue-200 dark:hover:bg-blue-950';
const errorText = error => typeof error?.data?.detail === 'string' ? error.data.detail : error?.message || '暂时无法读取，请重试。';
const percent = n => n == null ? '—' : `${(n * 100).toFixed(1)}%`;
const stamp = (seconds, timezone) => {
  if (seconds == null) return '未限定';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: timezone, dateStyle: 'medium', timeStyle: 'medium', hour12: false,
    }).format(new Date(seconds * 1000));
  } catch { return '无效时间'; }
};

export default function TimelineSummaryPanel({
  endpoint, scopeParams = {}, communication = false, title = '时间规律总结',
  loadSummary = getTimelineSummary, loadRecords = getTimelineSummaryRecords,
}) {
  const [zone, setZone] = useState('Asia/Shanghai');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [direction, setDirection] = useState('all');
  const [talker, setTalker] = useState('');
  const [eventSource, setEventSource] = useState('');
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [stale, setStale] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [selector, setSelector] = useState(null);
  const [dayPage, setDayPage] = useState(0);
  const requestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const dialogRef = useRef(null);
  const params = { ...scopeParams, timezone: zone, ...(startDate ? { start_date: startDate } : {}),
    ...(endDate ? { end_date: endDate } : {}), ...(communication ? { direction, ...(talker ? { talker } : {}) }
      : eventSource ? { event_source: eventSource } : {}) };
  const identity = JSON.stringify([endpoint, params]);
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const invalidRange = startDate && endDate && startDate > endDate;

  useEffect(() => {
    const requests = requestRef;
    const detailRequests = detailRequestRef;
    requestRef.current++;
    detailRequestRef.current++;
    setData(null); setError(null); setBusy(false); setStale(false);
    setDetail(null); setSelector(null); setDetailBusy(false); setDetailError(null); setDayPage(0);
    return () => { requests.current++; detailRequests.current++; };
  }, [identity]);

  const generate = async () => {
    if (invalidRange || busy) return;
    const request = ++requestRef.current;
    const requestedIdentity = identity;
    detailRequestRef.current++;
    setSelector(null); setDetail(null); setBusy(true); setError(null); setData(null);
    try {
      const result = await loadSummary(endpoint, params);
      if (request !== requestRef.current || identityRef.current !== requestedIdentity) return;
      setData(result); setStale(false); setDayPage(0);
    } catch (err) {
      if (request === requestRef.current && identityRef.current === requestedIdentity) setError(err);
    } finally {
      if (request === requestRef.current && identityRef.current === requestedIdentity) setBusy(false);
    }
  };
  const closeDetail = () => {
    detailRequestRef.current++;
    setSelector(null); setDetail(null); setDetailError(null); setDetailBusy(false);
  };
  const openRecords = async (next = {}, offset = 0) => {
    if (!data || stale) return;
    const request = ++detailRequestRef.current;
    const requestedIdentity = identity;
    setSelector(next); setDetail(null); setDetailError(null); setDetailBusy(true);
    const { direction: recordDirection, ...selection } = next;
    try {
      const result = await loadRecords(endpoint, { ...params, ...selection,
        ...(recordDirection ? { record_direction: recordDirection } : {}),
        source_version: data.context.source_version, summary_id: data.context.context_id, offset, limit: 50 });
      if (request === detailRequestRef.current && identityRef.current === requestedIdentity) setDetail(result);
    } catch (err) {
      if (request === detailRequestRef.current && identityRef.current === requestedIdentity) {
        setDetailError(err);
        if (err.status === 409) setStale(true);
      }
    } finally {
      if (request === detailRequestRef.current && identityRef.current === requestedIdentity) setDetailBusy(false);
    }
  };
  const dialogOpen = selector !== null;
  useEffect(() => {
    if (!dialogOpen) return undefined;
    const returnFocus = document.activeElement;
    dialogRef.current?.focus();
    const onKey = event => {
      if (event.key === 'Escape') {
        detailRequestRef.current++;
        setSelector(null); setDetail(null); setDetailBusy(false);
      }
      if (event.key !== 'Tab') return;
      const dialog = dialogRef.current;
      const elements = [...(dialog?.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]') || [])]
        .filter(e => e.getClientRects().length);
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || document.activeElement === dialog || !dialog.contains(document.activeElement)
        || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    };
  }, [dialogOpen]);

  const context = data?.context;
  const counts = context?.counts || {};
  const coverage = context?.coverage;
  const hours = data?.hours || [];
  const peak = Math.max(1, ...hours.map(h => h.count));
  const heatPeak = Math.max(1, ...(data?.heatmap || []).map(h => h.count));
  const daily = data?.daily || [];

  return <section aria-label={title} data-testid="timeline-summary" className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 text-slate-700 [overflow-wrap:anywhere] dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
    <header>
      <h2 className="flex items-center gap-2 text-lg font-semibold"><Clock size={18} />{title}</h2>
      <p className="mt-1 text-xs leading-6 text-slate-500 dark:text-slate-400">按所选来源记录统计，可回查具体记录。没有记录不等于没有活动；时间分布不直接证明具体人员行为。</p>
      <p className="text-xs">来源：{scopeParams.task_id ? `任务 ${scopeParams.task_id} · ${scopeParams.source === 'wechat' ? '微信派生记录' : '事件库'}` : communication ? '当前选中的通讯导入（不合并其他导入）' : '当前任务'}</p>
      {(scopeParams.start_time != null || scopeParams.end_time != null || scopeParams.event_type) &&
        <p className="mt-1 text-xs">页面已有筛选：{stamp(scopeParams.start_time, zone)} — {stamp(scopeParams.end_time, zone)}（{zone}，含边界）{scopeParams.event_type && ` · ${scopeParams.event_type}`}</p>}
    </header>
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-xs">分析时区<select aria-label="分析时区" className={`${field} mt-1 block`} value={zone} onChange={e => setZone(e.target.value)}>
        {['Asia/Shanghai', 'UTC', 'Asia/Hong_Kong', 'America/New_York', 'Europe/London'].map(z => <option key={z}>{z}</option>)}
      </select></label>
      <label className="text-xs">开始日期<input aria-label="总结开始日期" type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className={`${field} mt-1 block`} /></label>
      <label className="text-xs">结束日期<input aria-label="总结结束日期" type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className={`${field} mt-1 block`} /></label>
      {!communication && !scopeParams.event_source && <label className="text-xs">事件来源<select aria-label="事件来源" value={eventSource} onChange={e => setEventSource(e.target.value)} className={`${field} mt-1 block`}>
        <option value="">全部来源记录</option>
        {Object.entries({ FILE_SYSTEM: '文件系统', WEB_BROWSER: '浏览器', LINUX_SYSLOG: 'Linux日志',
          WINDOWS_EVENT_LOG: 'Windows日志', ANDROID_LOG: 'Android日志', SYSTEM: '系统',
          NETWORK: '网络', SECURITY: '安全事件', APPLICATION: '应用', UNKNOWN: '来源未知' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select></label>}
      {communication && <>
        <label className="text-xs">收发方向<select aria-label="收发方向" value={direction} onChange={e => setDirection(e.target.value)} className={`${field} mt-1 block`}>
          <option value="all">全部（含系统及未知）</option>{Object.entries(DIRECTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select></label>
        <label className="text-xs">会话账号或群标识<input aria-label="会话标识" value={talker} maxLength={256} onChange={e => setTalker(e.target.value)} className={`${field} mt-1 block max-w-full`} placeholder="留空统计当前来源全部会话" /></label>
      </>}
      <button type="button" className={button} data-testid="timeline-summary-generate" disabled={busy || !!invalidRange} onClick={generate}>
        {busy ? '正在统计…' : '生成时间线总结'}
      </button>
    </div>
    <p className="text-xs text-slate-500">日期按上述时区计算，并与页面已有时间及事件筛选取交集；修改条件后需重新生成。重复时段表示至少3个独立日期出现记录。</p>
    {invalidRange && <p role="alert">开始日期不能晚于结束日期。</p>}
    {error && <p role="alert" className="text-rose-700 dark:text-rose-300">{errorText(error)}</p>}
    {stale && <p role="alert" className="text-amber-800 dark:text-amber-300">来源或统计条件已变化，旧结果已停止回查。请重新生成时间线总结。</p>}
    {data && <div className="space-y-5" data-testid="timeline-summary-result" data-context-id={context.context_id}>
      <div className="rounded-xl bg-blue-50 p-4 dark:bg-blue-950/40">
        <p className="text-sm leading-7">{data.summary.text}</p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs" data-testid="timeline-quality">
          <button type="button" className="underline" disabled={stale} onClick={() => openRecords()}>有效 {counts.valid_records}</button>
          {[['missing', '时间缺失'], ['invalid', '时间无效'], ['inferred', '推定时间'], ['processing', '处理时间']].map(([key, label]) =>
            <button type="button" key={key} className="underline" disabled={stale || !counts[`${key}_records`]} onClick={() => openRecords({ quality: key })}>{label} {counts[`${key}_records`]}</button>)}
          <span>去重移除 {counts.duplicate_records}</span><span>标识冲突保留 {counts.identity_conflict_records}</span>
        </div>
        <p className="mt-2 text-xs leading-6">{coverage.quality_scope}</p>
      </div>
      {(coverage.truncated || coverage.daily_truncated || coverage.missing_tables.length > 0) &&
        <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200" data-testid="timeline-truncation">
          {coverage.truncated && <p>数据范围已截断：候选 {context.candidate_records} 条，扫描 {counts.scanned_records} 条，未扫描 {coverage.unscanned_records} 条。以下比例及规律仅适用于已扫描记录。</p>}
          {coverage.daily_truncated && <p>日期明细仅展示前 {coverage.displayed_days_limit} 个有记录日期，小时分布仍使用全部已扫描有效记录。</p>}
          {coverage.missing_tables.length > 0 && <p>缺少来源表：{coverage.missing_tables.join('、')}，不能视为没有相关记录。</p>}
        </div>}
      <div>
        <h3 className="font-semibold">时间分布 · 点击时段回查</h3>
        <div className="mt-3 grid grid-cols-12 gap-1 sm:grid-cols-[repeat(24,minmax(0,1fr))]">
          {hours.map(h => <button type="button" key={h.hour} disabled={stale || !h.count}
            aria-label={`${h.hour}时：${h.count}条，${h.observed_days}个日期`} title={`${h.count} 条，占 ${percent(h.share)}；${h.observed_days} 个日期`}
            onClick={() => openRecords(h.selector)} className="flex min-w-0 flex-col items-center rounded px-0.5 pt-1 text-[10px] hover:bg-blue-50 focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-slate-700">
            <span className="flex h-20 w-full items-end"><span className="block w-full rounded-t bg-blue-500" style={{ height: `${h.count / peak * 100}%`, minHeight: h.count ? 2 : 0 }} /></span>
            <span>{String(h.hour).padStart(2, '0')}</span><span>{h.count}</span>
          </button>)}
        </div>
        <p className="mt-2 text-xs text-slate-500">分母为本轮有效记录数。颜色深浅和柱高表示数量，不表示证据优先级。</p>
      </div>
      <div>
        <h3 className="font-semibold">重复时段</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {data.repeated_hours.map(h => <button type="button" key={h.hour} className={button} disabled={stale} onClick={() => openRecords(h.selector)}>
            {h.hour}:00—{h.hour + 1}:00 · {h.observed_days}/{h.observed_day_denominator} 个有记录日期 · {h.count} 条
          </button>)}
          {!data.repeated_hours.length && <p className="text-sm">尚未发现跨至少3个独立日期重复出现的时段，不能据此认定没有规律。</p>}
        </div>
      </div>
      <div>
        <h3 className="font-semibold">星期与小时分布</h3>
        <div className="mt-3 space-y-1" role="group" aria-label="星期小时热力图">
          {WEEKDAYS.map((day, d) => <div key={day} className="grid grid-cols-[2.5rem_repeat(24,minmax(0,1fr))] items-center gap-0.5">
            <span className="text-xs">{day}</span>
            {data.heatmap.filter(h => h.weekday === d).map(h => <button type="button" key={h.hour} disabled={stale || !h.count}
              aria-label={`${day} ${h.hour}时 ${h.count}条`} title={`${day} ${h.hour}时：${h.count}条`}
              onClick={() => openRecords(h.selector)} className="h-5 min-w-0 rounded-sm border border-blue-200 focus-visible:ring-2 focus-visible:ring-blue-600"
              style={{ backgroundColor: `rgba(59,130,246,${h.count ? 0.15 + 0.85 * h.count / heatPeak : 0.03})` }} />)}
          </div>)}
          <p className="text-right text-[10px] text-slate-500">从左至右：00—23时；空格表示当前统计没有记录，不代表没有活动。</p>
        </div>
      </div>
      {data.communication.available && <div>
        <h3 className="font-semibold">通讯收发规律</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {Object.entries(DIRECTIONS).map(([key, label]) => {
            const values = data.communication.hourly[key] || [];
            const max = Math.max(0, ...values);
            return <button type="button" key={key} disabled={stale || !data.communication.counts[key]} className={button} onClick={() => openRecords({ direction: key })}>
              {label} {data.communication.counts[key] || 0} 条{max > 0 && ` · 最多记录时段 ${values.indexOf(max)} 时（${max}条）`}
            </button>;
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">收到消息不证明当时正在操作；系统消息、未知方向单列。收发方向依据来源字段，不由模型推断。</p>
      </div>}
      <div>
        <h3 className="font-semibold">日期变化</h3>
        <p className="mt-1 text-xs text-slate-500">只列有记录日期；仅当相邻日也有记录时计算数量变化，缺失日期不补成“无活动”。</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs"><thead><tr><th className="p-2">日期</th><th>有效记录</th><th>较前一日</th><th>来源</th></tr></thead>
            <tbody>{daily.slice(dayPage * 20, (dayPage + 1) * 20).map(day => <tr key={day.day} className="border-t border-slate-100 dark:border-slate-700">
              <td className="whitespace-nowrap p-2">{day.day}</td><td>{day.count}</td>
              <td>{day.delta == null ? '前一日未见记录，覆盖未知' : `${day.delta > 0 ? '+' : ''}${day.delta}`}</td>
              <td><button type="button" disabled={stale} className="text-blue-700 underline dark:text-blue-300" onClick={() => openRecords(day.selector)}>查看记录</button></td>
            </tr>)}</tbody></table>
        </div>
        {!daily.length && <p className="mt-2 text-sm">没有可展示的有效日期记录。</p>}
        {daily.length > 20 && <div className="mt-2 flex items-center gap-2 text-xs">
          <button type="button" className={button} disabled={!dayPage} onClick={() => setDayPage(v => v - 1)}>上一页日期</button>
          <span>{dayPage + 1}/{Math.ceil(daily.length / 20)}</span>
          <button type="button" className={button} disabled={(dayPage + 1) * 20 >= daily.length} onClick={() => setDayPage(v => v + 1)}>下一页日期</button>
        </div>}
      </div>
      <ul className="list-disc space-y-1 pl-5 text-xs leading-6 text-slate-500 dark:text-slate-400">
        {data.warnings.map(w => <li key={w}>{w}</li>)}
      </ul>
      <details className="rounded-xl border border-slate-200 p-3 text-xs leading-6 dark:border-slate-600">
        <summary className="cursor-pointer font-medium">统计口径、来源版本与筛选条件</summary>
        <dl className="mt-3 space-y-1">
          <dt>来源范围</dt><dd>{context.scope.kind} · {context.scope.scope_id}</dd>
          <dt>记录来源层级</dt><dd>{context.scope.record_origin === 'derived_event_table' ? '提取后的事件表，非完整原始操作日志'
            : context.scope.record_origin === 'parsed_message_table' ? '解析后的消息表，记录标识属于派生结果'
              : '已导入的解密消息数据库副本'}</dd>
          <dt>分析时区／来源时间单位</dt><dd>{context.filters.timezone} · {context.scope.timestamp_unit}</dd>
          <dt>有效记录实际范围</dt><dd>{coverage.first_observed_time == null ? '无有效记录' : `${stamp(coverage.first_observed_time, zone)} — ${stamp(coverage.last_observed_time, zone)}`}</dd>
          <dt>筛选条件（可复核）</dt><dd className="font-mono">{JSON.stringify(context.filters)}</dd>
          <dt>去重规则</dt><dd>{context.deduplication.description} {context.deduplication.identity}</dd>
          <dt>统计版本</dt><dd>{context.statistics_version}</dd>
          <dt>来源版本（数据库及 WAL 文件状态指纹，非原始证据内容哈希）</dt><dd className="break-all font-mono">{context.source_version}</dd>
          <dt>已扫描字段投影哈希</dt><dd className="break-all font-mono">{context.scanned_content_hash}</dd>
          <dt>本轮统计标识（以上各项结果共用）</dt><dd className="break-all font-mono">{context.context_id}</dd>
          <dt>排除到时间范围之外／方向范围之外</dt><dd>{counts.outside_time_records}／{counts.outside_direction_records} 条</dd>
          <dt>扫描口径</dt><dd>先按事件类型或会话筛选，再按来源表及行号顺序扫描，最后应用时间与收发筛选；达到上限时仅统计已扫描部分。</dd>
          <dt>时间依据构成</dt><dd>{Object.entries(data.time_bases).map(([k, n]) => `${BASIS[k] || k} ${n}条`).join('；') || '无'}</dd>
        </dl>
      </details>
    </div>}
    {dialogOpen && <div className="fixed inset-0 z-[80] !m-0 flex justify-end" data-testid="timeline-source-overlay">
      <button type="button" tabIndex={-1} className="absolute inset-0 bg-slate-950/40" aria-label="关闭来源记录" onClick={closeDetail} />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="时间线来源回查" tabIndex={-1}
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-white p-5 outline-none [overflow-wrap:anywhere] dark:bg-slate-900">
        <header className="flex items-center justify-between gap-2"><h3 className="font-semibold">来源记录回查</h3><button type="button" aria-label="关闭回查" onClick={closeDetail}><X size={20} /></button></header>
        <p className="mt-2 text-xs text-slate-500">本轮筛选与来源版本一致的去重记录；不按同名文件猜测来源。</p>
        {detailBusy && <p className="mt-4" role="status">正在核对来源版本…</p>}
        {detailError && <p role="alert" className="mt-4 text-amber-800 dark:text-amber-300">{errorText(detailError)}</p>}
        {detail && <>
          <p className="mt-3 text-xs">符合条件 {detail.total} 条，当前显示 {detail.records.length} 条。统计版本 {detail.context.statistics_version}</p>
          <p className="mt-1 break-all text-[10px] text-slate-500">来源版本 {detail.context.source_version}</p>
          <div className="mt-4 space-y-3">{detail.records.map(record => <article key={record.record_ref} className="rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-600">
            <p className="font-mono text-xs">{record.record_ref} · 来源表记录标识 {record.original_id}</p>
            <p className="mt-2">{record.timestamp_iso || '时间不可用'} · {DIRECTIONS[record.direction] || record.event_type}</p>
            <p className="mt-1 text-xs">{BASIS[record.time_basis]}{record.talker && ` · 会话 ${record.talker}`}</p>
            {record.file_path && <p className="mt-1 break-all text-xs">{record.file_path}</p>}
            <pre className="mt-3 whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs leading-6 dark:bg-slate-800">{record.content || '本条记录没有可读正文。'}</pre>
            {record.content_truncated && <p className="text-xs text-amber-700 dark:text-amber-300">正文仅展示前8000字符，统计未按这段展示文本推算。</p>}
            <details className="mt-2 text-xs"><summary className="cursor-pointer">原字段与记录校验值</summary>
              <p className="mt-2">原始时间值：{String(record.timestamp_raw ?? '缺失')}</p>
              <pre className="mt-1 whitespace-pre-wrap break-all">{JSON.stringify(record.raw_fields, null, 2)}</pre>
              <p className="mt-1 break-all">本次读取字段 SHA-256：{record.record_sha256}</p>
            </details>
          </article>)}</div>
          {!detail.records.length && <p className="mt-3 text-sm">此条件下没有可回查记录，不能据此判断没有活动。</p>}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button type="button" className={button} disabled={stale || detail.selection.offset === 0} onClick={() => openRecords(selector, Math.max(0, detail.selection.offset - 50))}>上一页记录</button>
            <button type="button" className={button} disabled={stale || !detail.page_truncated} onClick={() => openRecords(selector, detail.selection.offset + 50)}>下一页记录</button>
            <button type="button" className={button} onClick={closeDetail}><RefreshCw size={12} className="mr-1 inline" />返回统计</button>
          </div>
        </>}
      </div>
    </div>}
  </section>;
}
