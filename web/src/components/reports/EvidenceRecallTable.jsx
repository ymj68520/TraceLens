// EvidenceRecallTable.jsx
// 首章「证据召回表」：deterministic manifest 字段（section.recall_table）的
// 只读渲染。表内每一行都对应一个已被某章引用的 citation_id，因此点击行内
// 引用标记与正文引用标记走同一条 exact 查表路径，不做文件名/正则推导。
import { ArrowUpRight, Table2 } from 'lucide-react';
import { PRIORITIES, TOPICS, priorityStyle } from './evidenceClassificationStyles';

const TYPE_LABELS = {
    document: '文档', chat_record: '聊天记录', transaction_record: '交易记录',
    image: '图片', log: '日志', android_artifact: 'Android 工件',
    other: '其他材料', unknown: '类型未定',
};
const STATUS_LABELS = { ready: '已冻结', partial: '部分可用', unavailable: '不可读' };

function TopicLabels({ topics }) {
    if (!topics?.length) return <span className="text-slate-400 dark:text-slate-500">—</span>;
    return (
        <span className="inline-flex flex-wrap gap-1">
            {topics.map(topic => (
                <span key={topic} className="rounded border border-slate-200 px-1 py-px text-[10px] leading-4 text-slate-600 dark:border-slate-600 dark:text-slate-300">
                    {TOPICS[topic] || '主题未定'}
                </span>
            ))}
        </span>
    );
}

export default function EvidenceRecallTable({ table, onOpenCitation, focusCitationId = null }) {
    if (!table) return null;
    const rows = table.rows || [];
    const coverage = table.total_materials
        ? Math.round((table.recalled_materials / table.total_materials) * 100)
        : 0;
    return (
        <section className="mt-6 rounded-xl border border-indigo-100 bg-indigo-50/30 dark:border-indigo-900/50 dark:bg-indigo-950/20" data-testid="evidence-recall-table" aria-label="证据召回表">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-indigo-100 px-4 py-3 dark:border-indigo-900/50">
                <h4 className="inline-flex items-center gap-2 text-sm font-semibold text-indigo-900 dark:text-indigo-100">
                    <Table2 size={15} aria-hidden />{table.title || '证据召回表'}
                </h4>
                <p className="text-[11px] text-slate-600 dark:text-slate-300">
                    入报 {table.total_materials} 份 · 进入正文 {table.recalled_materials} 份（{coverage}%）· 引用 {table.total_citations} 处
                    {table.unavailable_materials > 0 && ` · 不可读 ${table.unavailable_materials} 份`}
                </p>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem] border-collapse text-left text-xs">
                    <caption className="sr-only">本报告各章节实际引用的材料清单，按引用次数排序</caption>
                    <thead>
                        <tr className="border-b border-indigo-100 bg-white/60 text-[11px] text-slate-500 dark:border-indigo-900/50 dark:bg-slate-800/60 dark:text-slate-400">
                            <th scope="col" className="w-[13%] px-3 py-2 font-medium">引用</th>
                            <th scope="col" className="w-[35%] px-3 py-2 font-medium">材料</th>
                            <th scope="col" className="w-[18%] px-3 py-2 font-medium">类型 / 主题</th>
                            <th scope="col" className="w-[15%] px-3 py-2 font-medium">核查优先级</th>
                            <th scope="col" className="w-[9%] px-3 py-2 text-right font-medium">引用次数</th>
                            <th scope="col" className="w-[10%] px-3 py-2 text-right font-medium">涉及章节</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(row => {
                            const style = priorityStyle(row.priority);
                            return (
                                <tr key={row.citation_id} className="border-b border-indigo-50 last:border-0 dark:border-indigo-900/30" data-testid="recall-row">
                                    <td className="px-3 py-2 align-top">
                                        <button
                                            type="button"
                                            onClick={() => onOpenCitation?.(row.citation_id)}
                                            data-priority={PRIORITIES[row.priority] ? row.priority : 'unassessed'}
                                            data-testid={`recall-citation-${row.citation_id}`}
                                            aria-label={`查看引用 ${row.citation_id} 的证据溯源`}
                                            className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono font-semibold transition-all hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${style.tone} ${focusCitationId === row.citation_id ? 'ring-2 ring-amber-400 ring-offset-2 dark:ring-offset-slate-900' : ''}`}
                                        >
                                            {row.citation_id}
                                        </button>
                                    </td>
                                    <td className="px-3 py-2 align-top">
                                        <span className="block break-all font-medium leading-5 text-slate-800 dark:text-slate-100" title={row.evidence_key}>{row.evidence_name}</span>
                                        <span className="mt-0.5 block text-[10px] text-slate-500 dark:text-slate-400">
                                            {STATUS_LABELS[row.material_status] || '状态未知'}
                                        </span>
                                    </td>
                                    <td className="px-3 py-2 align-top">
                                        <span className="block text-slate-700 dark:text-slate-200">{TYPE_LABELS[row.material_type] || '类型未定'}</span>
                                        <span className="mt-1 block"><TopicLabels topics={row.topics} /></span>
                                    </td>
                                    <td className="px-3 py-2 align-top">
                                        <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold leading-4 ${style.tone}`}>{style.label}</span>
                                    </td>
                                    <td className="px-3 py-2 text-right align-top font-mono text-slate-700 dark:text-slate-200">{row.reference_count}</td>
                                    <td className="px-3 py-2 text-right align-top font-mono text-slate-700 dark:text-slate-200">{row.chapter_count}</td>
                                </tr>
                            );
                        })}
                        {!rows.length && (
                            <tr>
                                <td colSpan={6} className="px-3 py-6 text-center text-slate-500 dark:text-slate-400">本轮没有材料进入章节结论。</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
            {!!table.notes?.length && (
                <ul className="space-y-1 border-t border-indigo-100 px-4 py-3 text-[11px] leading-5 text-slate-600 dark:border-indigo-900/50 dark:text-slate-300">
                    {table.notes.map(note => <li key={note} className="flex gap-1.5"><ArrowUpRight size={12} className="mt-1 shrink-0" aria-hidden />{note}</li>)}
                </ul>
            )}
        </section>
    );
}
