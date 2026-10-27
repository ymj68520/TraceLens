export default function DeliveryQualityPanel({ quality }) {
  const value = quality || { status: 'unassessed', label: '尚未评估', reasons: ['本版本没有独立质量记录，执行完成不等于结论已核实。'] };
  return <section aria-label="交付质量" className="rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700">
    <p className="font-semibold">交付质量：{value.label}</p>
    {!!value.reasons?.length && <details className="mt-2 text-xs text-slate-600 dark:text-slate-300"><summary>查看 {value.reasons.length} 项质量说明</summary><ul className="mt-2 space-y-1">{value.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul></details>}
    {value.counts && <p className="mt-2 text-xs">冻结来源 {value.counts.sources ?? '未记录'} · 本轮提取完成 {value.counts.extracted ?? '未记录'} · 部分完成 {value.counts.partial ?? '未记录'} · 暂缓 {value.counts.deferred ?? '未记录'} · 不可用 {value.counts.unavailable ?? '未记录'}</p>}
    {value.scope && <p className="mt-1 text-xs text-slate-500">{value.scope}</p>}
  </section>;
}
