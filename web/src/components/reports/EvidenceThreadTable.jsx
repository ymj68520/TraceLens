// EvidenceThreadTable.jsx
// 首章「案情线索与研判方向」表：案件级线索聚合（每个已校验方向恰好归入一条
// 线索），只读渲染 manifest 的 section.thread_table。线索内的具体值
// （地址:端口、配置键=值、账号）全部逐字锚定在冻结引文中；章节号为可点击
// 锚点，点击滚动到对应章节卡片。
import { Crosshair, Table2 } from 'lucide-react';

export default function EvidenceThreadTable({ table, onJumpToChapter }) {
    if (!table) return null;
    const rows = table.rows || [];
    const coverage = table.total_directions
        ? Math.round((table.covered_directions / table.total_directions) * 100)
        : 0;
    return (
        <section className="mt-6 rounded-xl border border-indigo-100 bg-indigo-50/30 dark:border-indigo-900/50 dark:bg-indigo-950/20" data-testid="evidence-thread-table" aria-label="案情线索与研判方向">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-indigo-100 px-4 py-3 dark:border-indigo-900/50">
                <h4 className="inline-flex items-center gap-2 text-sm font-semibold text-indigo-900 dark:text-indigo-100">
                    <Table2 size={15} aria-hidden />{table.title || '案情线索与研判方向'}
                </h4>
                <p className="text-[11px] text-slate-600 dark:text-slate-300">
                    研判方向 {table.total_directions} 项 · 已归入线索 {table.covered_directions} 项（{coverage}%）
                </p>
            </div>
            <ol className="divide-y divide-indigo-50 dark:divide-indigo-900/30">
                {rows.map((row, index) => (
                    <li key={`${row.name}-${index}`} className="px-4 py-3" data-testid="thread-row">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <h5 className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                                <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-100 font-mono text-[10px] font-bold text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-200">{String(index + 1).padStart(2, '0')}</span>
                                {row.name}
                            </h5>
                            <span className="text-[10px] text-slate-500 dark:text-slate-400">
                                {row.direction_count} 项方向 · {row.material_count} 份材料
                                {row.chapter_numbers?.length ? ` · 第 ${row.chapter_numbers.join('、')} 章` : ''}
                            </span>
                        </div>
                        <p className="mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-6 text-slate-700 dark:text-slate-200" data-testid="thread-contribution">{row.contribution}</p>
                        {!!row.key_facts?.length && (
                            <p className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="关键事实">
                                <Crosshair size={11} className="text-indigo-400" aria-hidden />
                                {row.key_facts.map(fact => (
                                    <code key={fact} className="max-w-full truncate rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] leading-4 text-slate-700 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200" title={fact}>{fact}</code>
                                ))}
                            </p>
                        )}
                        {!!row.chapter_numbers?.length && (
                            <p className="mt-1.5 flex flex-wrap items-center gap-1 text-[10px] text-slate-500 dark:text-slate-400">
                                见
                                {row.chapter_numbers.map(num => (
                                    <button key={num} type="button"
                                        onClick={() => onJumpToChapter?.(num)}
                                        data-testid={`thread-chapter-${num}`}
                                        className="rounded border border-indigo-200 px-1 py-px font-mono text-[10px] font-semibold text-indigo-700 hover:bg-indigo-50 dark:border-indigo-800 dark:text-indigo-200 dark:hover:bg-indigo-900/40">
                                        第 {num} 章
                                    </button>
                                ))}
                            </p>
                        )}
                    </li>
                ))}
                {!rows.length && (
                    <li className="px-4 py-6 text-center text-sm text-slate-500 dark:text-slate-400">本轮没有可归入线索的调查方向。</li>
                )}
            </ol>
            {!!table.notes?.length && (
                <ul className="space-y-1 border-t border-indigo-100 px-4 py-3 text-[11px] leading-5 text-slate-600 dark:border-indigo-900/50 dark:text-slate-300">
                    {table.notes.map(note => <li key={note}>{note}</li>)}
                </ul>
            )}
        </section>
    );
}
