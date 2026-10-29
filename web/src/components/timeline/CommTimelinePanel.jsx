import { useCallback, useEffect, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { RefreshCw } from 'lucide-react';
import { getCommTimeline } from '../../services/commGraphService';

const KINDS = [
    { id: 'call', label: '通话' },
    { id: 'sms', label: '短信' },
    { id: 'im_private', label: '私聊' },
    { id: 'im_group', label: '群消息' },
    { id: 'im_artifact', label: 'IM 工件' },
];

const DIRECTION_LABEL = {
    sent: '发出', received: '收到', unknown: '未知', mixed: '双向',
};

const fmtTime = (seconds) => {
    if (!seconds) return '—';
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
        + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

/** Local datetime-local value -> epoch seconds; undefined when empty/invalid. */
const toEpochSeconds = (value) => {
    if (!value) return undefined;
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : undefined;
};

/**
 * 案件通讯时间线：逐条记录（不是统计）。
 *
 * 所有时间由后端按来源契约换算成秒；同日记录按数据集与原始记录标识稳定
 * 排序。没有有效时间的记录不会出现在流里，覆盖度会给出扫描与过滤数量。
 */
export default function CommTimelinePanel({ taskId, wechatImports = [], qqImports = [] }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [kinds, setKinds] = useState([]);
    const [range, setRange] = useState({ start: '', end: '' });

    const importKey = useMemo(() => JSON.stringify([wechatImports, qqImports]), [wechatImports, qqImports]);

    const load = useCallback(async () => {
        if (!taskId) return;
        const startTime = toEpochSeconds(range.start);
        const endTime = toEpochSeconds(range.end);
        if ((range.start && startTime === undefined) || (range.end && endTime === undefined)) {
            setError('时间格式不完整');
            return;
        }
        if (startTime !== undefined && endTime !== undefined && startTime > endTime) {
            setError('开始时间不能晚于结束时间');
            return;
        }
        setLoading(true);
        setError('');
        try {
            const result = await getCommTimeline(taskId, {
                wechatImports, qqImports, kinds, startTime, endTime, limit: 500,
            });
            setData(result);
        } catch (err) {
            setError(err?.data?.detail || err?.message || '获取通讯时间线失败');
            setData(null);
        } finally {
            setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskId, importKey, kinds, range.start, range.end]);

    useEffect(() => { load(); }, [load]);

    const toggleKind = (id) => {
        setKinds((current) => current.includes(id)
            ? current.filter((item) => item !== id)
            : [...current, id]);
    };

    const coverage = data?.coverage;

    return (
        <section className="space-y-4" aria-label="案件通讯时间线">
            <div className="flex flex-wrap items-end gap-3">
                <label className="text-xs">开始
                    <input type="datetime-local" aria-label="时间线开始时间" value={range.start}
                        onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}
                        className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" />
                </label>
                <label className="text-xs">结束
                    <input type="datetime-local" aria-label="时间线结束时间" value={range.end}
                        onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}
                        className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" />
                </label>
                <div className="flex flex-wrap gap-1" role="group" aria-label="记录类型筛选">
                    {KINDS.map((kind) => (
                        <button key={kind.id} type="button"
                            aria-pressed={kinds.includes(kind.id)}
                            onClick={() => toggleKind(kind.id)}
                            className={`rounded-full border px-2 py-1 text-xs ${kinds.includes(kind.id)
                                ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-200'
                                : 'border-slate-300 text-slate-600 dark:border-slate-600 dark:text-slate-300'}`}>
                            {kind.label}
                        </button>
                    ))}
                </div>
                <button type="button" onClick={load} disabled={loading}
                    className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                    <RefreshCw size={14} /> {loading ? '加载中…' : '刷新'}
                </button>
            </div>

            {error && <p role="alert" className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}

            {coverage && (
                <div className="rounded-xl border border-slate-200 p-3 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300">
                    <p>
                        记录：返回 {coverage.records_returned} / 命中 {coverage.records_total}
                        {coverage.records_truncated > 0 && `（超出上限 ${coverage.records_truncated} 条未显示）`}
                    </p>
                    <p className="mt-1">
                        扫描 {coverage.records_scanned ?? 0} 条 · 类型过滤 {coverage.filtered_kind ?? 0} 条 ·
                        时间过滤 {coverage.filtered_time ?? 0} 条 · 去重 {coverage.duplicates ?? 0} 条
                    </p>
                    <p className="mt-1 text-slate-400">
                        去重口径 {coverage.dedup_rule}；同一句话出现在两个数据集时保留为两条记录。
                    </p>
                    {data.sources?.some((source) => source.status === 'unreadable') && (
                        <p className="mt-1 text-amber-700 dark:text-amber-300">
                            有数据集不可读取，未计入结果。
                        </p>
                    )}
                </div>
            )}

            {data && data.records.length === 0 && (
                <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    当前筛选下没有通讯记录。没有记录不等于没有联系，请检查数据集与时间范围。
                </p>
            )}

            {data && data.records.length > 0 && (
                <div className="h-[520px] rounded-xl border border-slate-200 dark:border-slate-700">
                    <Virtuoso
                        data={data.records}
                        itemContent={(_, record) => (
                            <div className="flex gap-3 border-b border-slate-100 px-3 py-2 text-sm dark:border-slate-800">
                                <span className="w-36 shrink-0 text-xs text-slate-400">{fmtTime(record.timestamp)}</span>
                                <span className="w-16 shrink-0 text-xs text-slate-500">{record.kind_label}</span>
                                <span className="shrink-0 text-xs text-slate-500">{DIRECTION_LABEL[record.direction] || record.direction}</span>
                                <span className="min-w-0 flex-1 break-words text-slate-700 dark:text-slate-200">
                                    <span className="font-medium">{record.actor}</span>
                                    {' → '}
                                    <span className="font-medium">{record.peer}</span>
                                    {record.summary && <span className="text-slate-500">：{record.summary}</span>}
                                </span>
                                <span className="w-20 shrink-0 text-[10px] text-slate-400">{record.dataset}</span>
                            </div>
                        )}
                    />
                </div>
            )}
        </section>
    );
}
