import { useState } from 'react';

const kinds = { observation: '材料观察', inference: '模型推断', hypothesis: '待核假设' };
const status = { extracted: '已完成本轮提取', partial: '部分完成', deferred: '暂缓', unavailable: '不可用' };
export default function ReportOrganizationPanel({ organization, onOpenMaterial }) {
  const [expanded, setExpanded] = useState(false);
  if (!organization) return null;
  return <section className="rounded-2xl border border-blue-200 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-950/20" aria-label="报告组织与覆盖">
    <p className="font-semibold">{organization.quality === 'preliminary' ? '初步研判 · 存在未完成范围' : '待人工复核'}</p>
    <p className="mt-2 text-sm leading-7">{organization.quality_message}</p>
    <p className="mt-2 text-xs text-slate-500">正文 {organization.body_chars} 字符 · 附录 {organization.appendix_chars} 字符 · {organization.plan?.chapters?.length || 0} 个主体章节 · 最大单章占比 {Math.round((organization.validation?.max_section_share || 0) * 100)}%</p>
    <button className="mt-3 text-sm text-blue-700 dark:text-blue-300" onClick={() => setExpanded(!expanded)}>{expanded ? '收起来源与覆盖审计' : '查看来源与覆盖审计'}</button>
    {expanded && <div className="mt-3 max-h-[34rem] space-y-3 overflow-auto">
      <p className="text-xs">模型派发 {organization.usage?.calls ?? 0}/{organization.budget?.max_calls} 次；令牌预留上界 {organization.usage?.reserved_tokens ?? 0}。该数值不是实际计费。</p>
      {organization.validation?.execution_policy && <div className="space-y-1 text-xs" aria-label="报告并发与全文收束">
        <p>事实提取 {organization.validation.execution_policy.extraction_concurrency} 路 · 主体写作 {organization.validation.execution_policy.writing_concurrency} 路 · 逐章复核 {organization.validation.execution_policy.review_concurrency} 路。</p>
        <p>概述与结论在主体完成后收束，绑定最终主体版本。</p>
        <p>全文辅助复核：{organization.validation.coherence_status === 'auxiliary_checks_passed' ? '检查通过，关键结论仍需人工核对' : '未完成，请核对质量限制'}。</p>
        {!!organization.validation.coherence_advisories?.length && <details><summary>全文组织建议 · {organization.validation.coherence_advisories.length} 项</summary>
          {organization.validation.coherence_advisories.map((item,index) => <div key={index} className="mt-2 space-y-1">
            <p>{organization.plan?.chapters?.find(c => c.section_id===item.section_id)?.heading || '相关章节'} · {item.kind === 'repetition' ? '重复表述建议' : '衔接建议'}</p>
            <p>原段落片段：{item.quote}</p><p>{item.reason}</p>
          </div>)}
        </details>}
      </div>}
      {(organization.warnings || []).map((warning, index) => <p key={index} className="text-xs text-amber-800 dark:text-amber-300">{warning}</p>)}
      <details><summary>本轮发现及正文安排 · {organization.findings?.length || 0} 项</summary>
        {(organization.findings || []).map(item => <div key={item.finding_id} className="mt-2 rounded border border-slate-200 p-3 text-sm dark:border-slate-700">
          <p className="text-xs text-slate-500">{kinds[item.kind] || '待核'} · {organization.plan?.finding_disposition?.[item.finding_id]}</p>
          <p className="mt-1 leading-7">{item.statement}</p>
          {!!item.limitations?.length && <p className="text-xs">限制：{item.limitations.join('；')}</p>}
          {!!item.counter_spans?.length && <p className="text-xs text-amber-700">含反向或限制片段，需与正文解释一并核对。</p>}
        </div>)}
      </details>
      <details><summary>材料覆盖与未展开原因 · {organization.coverage?.length || 0} 项</summary>
        {(organization.coverage || []).map(item => <p key={item.material_id} className="mt-2 text-xs leading-6">
          <button className="text-blue-700 dark:text-blue-300" onClick={() => onOpenMaterial?.(item.material_id)}>{item.evidence_key}</button>
          {' · '}{status[item.status] || '待核对'} · {item.body_status === 'main' ? '正文已交代' : '附录保留'} · {item.exclusion_reason || item.reason}
        </p>)}
      </details>
    </div>}
  </section>;
}
