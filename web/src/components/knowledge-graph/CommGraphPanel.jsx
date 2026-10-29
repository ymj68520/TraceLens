import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { RefreshCw } from 'lucide-react';
import { getCommEdgeDetail, getCommGraph } from '../../services/commGraphService';

const RELATION_STYLE = {
    call: { color: '#38bdf8', label: '通话', dash: [] },
    sms: { color: '#a78bfa', label: '短信', dash: [] },
    im_private: { color: '#34d399', label: '私聊', dash: [] },
    im_group: { color: '#fbbf24', label: '群消息', dash: [3, 2] },
    im_artifact: { color: '#f472b6', label: 'IM 记录', dash: [3, 2] },
    group_member: { color: '#64748b', label: '群成员', dash: [2, 3] },
};

const COMMUNITY_COLORS = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b',
    '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

const escape = (value) => String(value ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/**
 * Convert a `<input type="datetime-local">` value (local wall clock) to epoch
 * seconds. Returns null for empty input and NaN-free values only: a partial
 * value like "2026-03-" must not silently become 0 or NaN on the wire.
 */
export const toEpochSeconds = (value) => {
    if (!value) return undefined;
    const parsed = new Date(value).getTime();
    if (!Number.isFinite(parsed)) return undefined;
    return Math.floor(parsed / 1000);
};

const fmtTime = (seconds) => {
    if (!seconds) return '—';
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
        + `${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

/**
 * 综合通讯关系图：手机检材 + 微信/QQ 导入合成一张图。
 *
 * 人物只在强标识（号码 / wxid / QQ 号）一致时合并；同名不同号码会作为
 * 待确认候选列出，不会自动合并。节点/边的上限、被截断的数量与不可读的
 * 数据集都在覆盖度里显式展示。
 */
export default function CommGraphPanel({ taskId, wechatImports = [], qqImports = [] }) {
    const [graph, setGraph] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [selected, setSelected] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [range, setRange] = useState({ start: '', end: '' });
    const container = useRef(null);
    const [width, setWidth] = useState(600);

    const importKey = useMemo(() => JSON.stringify([wechatImports, qqImports]), [wechatImports, qqImports]);

    const load = useCallback(async () => {
        if (!taskId) return;
        const startTime = toEpochSeconds(range.start);
        const endTime = toEpochSeconds(range.end);
        if (range.start && startTime === undefined) {
            setError('开始时间格式不完整');
            return;
        }
        if (range.end && endTime === undefined) {
            setError('结束时间格式不完整');
            return;
        }
        if (startTime !== undefined && endTime !== undefined && startTime > endTime) {
            setError('开始时间不能晚于结束时间');
            return;
        }
        setLoading(true);
        setError('');
        try {
            const result = await getCommGraph(taskId, {
                wechatImports, qqImports, startTime, endTime,
            });
            setGraph(result);
        } catch (err) {
            setError(err?.data?.detail || err?.message || '获取通讯关系图失败');
            setGraph(null);
        } finally {
            setLoading(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskId, importKey, range.start, range.end]);

    useEffect(() => { load(); }, [load]);

    useEffect(() => {
        if (!container.current) return undefined;
        const resize = () => setWidth(Math.max(240, container.current?.clientWidth || 600));
        resize();
        const observer = new ResizeObserver(resize);
        observer.observe(container.current);
        return () => observer.disconnect();
    }, []);

    const canvasData = useMemo(() => {
        if (!graph) return { nodes: [], links: [] };
        const communityOf = new Map();
        (graph.communities || []).forEach((members, index) => {
            members.forEach((id) => communityOf.set(id, index));
        });
        const nodes = graph.nodes.map((node) => ({
            ...node,
            name: node.label,
            community: communityOf.get(node.id) ?? -1,
        }));
        const links = graph.edges.map((edge) => ({
            ...edge,
            source: edge.source,
            target: edge.target,
        }));
        return { nodes, links };
    }, [graph]);

    const openEdge = useCallback(async (edge) => {
        setSelected({ kind: 'edge', edge });
        setDetail(null);
        setDetailLoading(true);
        try {
            const result = await getCommEdgeDetail(taskId,
                { source: edge.source, target: edge.target, relation: edge.relation },
                { wechatImports, qqImports });
            setDetail(result);
        } catch (err) {
            setDetail({ error: err?.data?.detail || err?.message || '回查失败', records: [] });
        } finally {
            setDetailLoading(false);
        }
    }, [taskId, importKey, wechatImports, qqImports]);

    const coverage = graph?.coverage;
    const nodes = graph?.nodes?.length || 0;

    return (
        <section className="space-y-4" aria-label="综合通讯关系图">
            <div className="flex flex-wrap items-end gap-3">
                <label className="text-xs">开始
                    <input type="datetime-local" aria-label="开始时间" value={range.start}
                        onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}
                        className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" />
                </label>
                <label className="text-xs">结束
                    <input type="datetime-local" aria-label="结束时间" value={range.end}
                        onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}
                        className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" />
                </label>
                <button type="button" onClick={load} disabled={loading}
                    className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                    <RefreshCw size={14} /> {loading ? '加载中…' : '刷新'}
                </button>
                <p className="text-xs text-slate-500">
                    仅按号码 / wxid / QQ 号一致合并人物；同名不同号码列为待确认。
                </p>
            </div>

            {error && <p role="alert" className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}

            {loading && !graph && <p className="text-sm text-slate-500">正在读取通讯数据…</p>}

            {graph && nodes === 0 && (
                <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    当前数据集没有可展示的通讯关系。没有记录不等于没有联系：请核对下方覆盖度与数据集状态。
                </p>
            )}

            {graph && nodes > 0 && (
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                    <div ref={container} className="min-w-0 overflow-hidden rounded-xl bg-slate-950">
                        <ForceGraph2D
                            width={width}
                            height={460}
                            graphData={canvasData}
                            backgroundColor="#0f172a"
                            nodeLabel={(node) => `${escape(node.label)}${node.is_owner ? ' · 本人' : ''} · 消息 ${node.message_count ?? 0} / 通话 ${node.call_count ?? 0} / 短信 ${node.sms_count ?? 0}`}
                            nodeColor={(node) => node.kind === 'owner' ? '#fbbf24'
                                : node.kind === 'group' ? '#64748b'
                                    : COMMUNITY_COLORS[((node.community ?? -1) + COMMUNITY_COLORS.length) % COMMUNITY_COLORS.length]}
                            nodeCanvasObjectMode={() => 'after'}
                            nodeCanvasObject={(node, ctx, scale) => {
                                if (scale < 1.2 && !node.is_owner) return;
                                ctx.fillStyle = '#e2e8f0';
                                ctx.textAlign = 'center';
                                ctx.font = `${Math.max(10 / scale, 3)}px sans-serif`;
                                ctx.fillText(node.label, node.x, node.y + 10 / scale);
                            }}
                            nodePointerAreaPaint={(node, color, ctx) => {
                                ctx.beginPath();
                                ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
                                ctx.fillStyle = color;
                                ctx.fill();
                            }}
                            linkColor={(link) => RELATION_STYLE[link.relation]?.color || '#94a3b8'}
                            linkLineDash={(link) => RELATION_STYLE[link.relation]?.dash || []}
                            linkWidth={(link) => Math.max(1, Math.min(6, Math.log2((link.weight || 1) + 1)))}
                            linkDirectionalArrowLength={3}
                            linkDirectionalArrowRelPos={1}
                            linkLabel={(link) => `${RELATION_STYLE[link.relation]?.label || link.relation} · ${link.weight} 条 · 点击回查`}
                            onLinkClick={openEdge}
                            onNodeClick={(node) => setSelected({ kind: 'node', node })}
                            cooldownTicks={80}
                        />
                    </div>

                    <aside className="space-y-3 text-sm">
                        <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                            <h3 className="text-xs font-semibold text-slate-500">覆盖度</h3>
                            <ul className="mt-2 space-y-1 text-xs text-slate-600 dark:text-slate-300">
                                <li>数据集：可读 {coverage.datasets_readable} / 共 {coverage.datasets_total}</li>
                                <li>节点：显示 {coverage.nodes_shown} / 共 {coverage.nodes_total}
                                    {coverage.nodes_truncated > 0 && `（截断 ${coverage.nodes_truncated}）`}</li>
                                <li>边：显示 {coverage.edges_shown} / 共 {coverage.edges_total}
                                    {coverage.edges_truncated > 0 && `（截断 ${coverage.edges_truncated}）`}</li>
                                <li>记录：通话 {coverage.calls_read} · 短信 {coverage.sms_read} · 消息 {coverage.messages_read} · IM 工件 {coverage.artifacts_read}</li>
                                <li>无可关联标识的记录：{coverage.orphan_records ?? 0}</li>
                                <li>无 IM 机主信息的数据集：{coverage.owner_unknown_datasets ?? 0}</li>
                            </ul>
                        </div>

                        {graph.candidates?.length > 0 && (
                            <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
                                <h3 className="text-xs font-semibold">同名待确认（{graph.candidates.length}）</h3>
                                <ul className="mt-1 space-y-1 text-xs">
                                    {graph.candidates.slice(0, 6).map((c) => (
                                        <li key={`${c.left}-${c.right}`}>{c.name}：两个不同身份，未自动合并</li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {graph.datasets?.map((dataset) => (
                            <div key={dataset.dataset_id} className="rounded-xl border border-slate-200 p-3 text-xs dark:border-slate-700">
                                <div className="font-medium text-slate-700 dark:text-slate-200">{dataset.label}</div>
                                <div className="mt-1 text-slate-500">{dataset.kind} · {dataset.dataset_id}</div>
                            </div>
                        ))}

                        {selected?.kind === 'node' && (
                            <div className="rounded-xl border border-slate-200 p-3 text-xs dark:border-slate-700">
                                <h3 className="font-semibold text-slate-700 dark:text-slate-200">{selected.node.label}</h3>
                                <p className="mt-1 text-slate-500">
                                    消息 {selected.node.message_count} · 通话 {selected.node.call_count} · 短信 {selected.node.sms_count}
                                </p>
                                <p className="mt-1 text-slate-500">首次 {fmtTime(selected.node.first_time)} · 最近 {fmtTime(selected.node.last_time)}</p>
                                <ul className="mt-1 space-y-0.5 text-slate-500">
                                    {Object.entries(selected.node.identities || {}).map(([kind, values]) => (
                                        <li key={kind}>{kind}: {values.join('、')}</li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {selected?.kind === 'edge' && (
                            <div className="rounded-xl border border-slate-200 p-3 text-xs dark:border-slate-700">
                                <h3 className="font-semibold text-slate-700 dark:text-slate-200">
                                    {RELATION_STYLE[selected.edge.relation]?.label || selected.edge.relation} · {selected.edge.weight} 条
                                </h3>
                                <p className="mt-1 text-slate-500">
                                    来源 {selected.edge.dataset} · 方向 {selected.edge.direction} · 时长 {selected.edge.duration_seconds}s
                                </p>
                                {detailLoading && <p className="mt-2 text-slate-500">回查中…</p>}
                                {detail?.error && <p role="alert" className="mt-2 text-rose-700">{detail.error}</p>}
                                {detail && !detail.error && (
                                    <>
                                        <p className="mt-2 text-slate-500">
                                            匹配 {detail.total} 条{detail.truncated > 0 && `，仅显示前 ${detail.records.length} 条`}
                                        </p>
                                        <ul className="mt-1 max-h-64 space-y-1 overflow-auto">
                                            {detail.records.map((record) => (
                                                <li key={record.record_ref} className="border-t border-slate-100 pt-1 dark:border-slate-700">
                                                    <span className="text-slate-400">{fmtTime(record.timestamp)}</span>
                                                    {' '}{record.summary || '（无正文）'}
                                                    <div className="text-[10px] text-slate-400">{record.record_ref}</div>
                                                </li>
                                            ))}
                                        </ul>
                                    </>
                                )}
                            </div>
                        )}
                    </aside>
                </div>
            )}
        </section>
    );
}
