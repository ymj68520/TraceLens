// EvidenceRecallTable.jsx
// 首章「证据召回表」：deterministic manifest 字段（section.recall_table）的
// 只读渲染。表内每一行都对应一个已被某章引用的 citation_id，因此点击行内
// 引用标记与正文引用标记走同一条 exact 查表路径，不做文件名/正则推导。
import { ArrowUpRight, Table2 } from 'lucide-react';
import { PRIORITIES, TOPICS, priorityStyle } from './evidenceClassificationStyles';

// The priority columns became a footnote inside the contribution cell, so these
// two helpers keep the tone/label semantics in one place without a separate
// column per attribute.
const priorityTone = (value) => priorityStyle(value).tone;
const priorityLabel = (value) => priorityStyle(value).label;

const TYPE_LABELS = {
    document: '文档', chat_record: '聊天记录', transaction_record: '交易记录',
    image: '图片', log: '日志', android_artifact: 'Android 工件',
    other: '其他材料', unknown: '类型未定',
};
const STATUS_LABELS = { ready: '已冻结', partial: '部分可用', unavailable: '不可读' };

function TopicLabels({ topics }) {
    if (!topics?.length) return null;
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
                <table className="w-full min-w-[44rem] border-collapse text-left text-xs">
                    <caption className="sr-only">本报告各章节实际引用的材料清单，以及每份材料在本次研判中支撑的结论</caption>
                    <thead>
                        <tr className="border-b border-indigo-100 bg-white/60 text-[11px] text-slate-500 dark:border-indigo-900/50 dark:bg-slate-800/60 dark:text-slate-400">
                            <th scope="col" className="w-[9%] px-3 py-2 font-medium">引用</th>
                            <th scope="col" className="w-[22%] px-3 py-2 font-medium">材料</th>
                            <th scope="col" className="px-3 py-2 font-medium">对本案的作用</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(row => (
                            <tr key={row.citation_id} className="border-b border-indigo-50 last:border-0 dark:border-indigo-900/30" data-testid="recall-row">
                                <td className="px-3 py-2.5 align-top">
                                    <button
                                        type="button"
                                        onClick={() => onOpenCitation?.(row.citation_id)}
                                        data-priority={PRIORITIES[row.priority] ? row.priority : 'unassessed'}
                                        data-testid={`recall-citation-${row.citation_id}`}
                                        aria-label={`查看引用 ${row.citation_id} 的证据溯源`}
                                        className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono font-semibold transition-all hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${priorityTone(row.priority)} ${focusCitationId === row.citation_id ? 'ring-2 ring-amber-400 ring-offset-2 dark:ring-offset-slate-900' : ''}`}
                                    >
                                        {row.citation_id}
                                    </button>
                                </td>
                                <td className="px-3 py-2.5 align-top">
                                    <span className="block break-all font-medium leading-5 text-slate-800 dark:text-slate-100" title={row.evidence_key}>{row.evidence_name}</span>
                                    <span className="mt-1 block text-[10px] text-slate-500 dark:text-slate-400">
                                        {TYPE_LABELS[row.material_type] || '类型未定'} · {STATUS_LABELS[row.material_status] || '状态未知'}
                                    </span>
                                    <span className="mt-1 block"><TopicLabels topics={row.topics} /></span>
                                </td>
                                <td className="px-3 py-2.5 align-top">
                                    <p className="whitespace-pre-wrap break-words leading-6 text-slate-700 dark:text-slate-200" data-testid="recall-contribution">{row.contribution || '本轮未记录该材料的具体作用。'}</p>
                                    {/* 计数降为脚注：读者要的是"它起了什么作用"，次数只是佐证强度。 */}
                                    <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                                        被引 {row.reference_count} 处 · 涉及 {row.chapter_count} 章 · {priorityLabel(row.priority)}
                                    </p>
                                </td>
                            </tr>
                        ))}
                        {!rows.length && (
                            <tr>
                                <td colSpan={3} className="px-3 py-6 text-center text-slate-500 dark:text-slate-400">本轮没有材料进入章节结论。</td>
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
