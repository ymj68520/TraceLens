import { Link } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import { edgeLabel, eventKinds } from './eventGraphConstants';

const sourceNames = { initial_analysis_summary: '初次分析摘要；尚未核对原文', android_record: 'Android 工件快照', text: '冻结文本', parsed_text: '解析文本（覆盖范围可能不完整）', machine_transcript: '机器转写（待核）', machine_visual_text: '机器读取图片文字（待核）' };

export default function EventGraphDetail({ taskId, detail, error, onClose }) {
  const panel = useRef(null);
  useEffect(() => {
    panel.current?.scrollIntoView?.({ block: 'nearest' });
    panel.current?.focus({ preventScroll: true });
  }, []);
  return <section ref={panel} tabIndex={-1} className="min-w-0 rounded-xl border border-slate-300 p-4 dark:border-slate-600" aria-label="图谱来源详情" data-testid="event-source-detail">
    <div className="flex items-start justify-between gap-3"><h3 className="font-semibold">图谱来源回查</h3><button type="button" className="text-blue-600" onClick={onClose}>关闭详情</button></div>
    {error && <p role="alert" className="text-orange-700">{error}</p>}
    {!detail && !error && <p>正在读取准确版本…</p>}
    {detail && <div className="mt-3 space-y-3 break-words [overflow-wrap:anywhere]">
      <p className="font-semibold">{detail.target.name || edgeLabel(detail.target)}</p>
      <p className="text-xs">{eventKinds[detail.target.kind] || edgeLabel(detail.target)} · {detail.run_id ? `冻结分析版本 ${detail.run_id}` : '当前已登记数据'}</p>
      {(detail.target.endpoints || []).map(node => <p className="text-sm" key={node.id}>{eventKinds[node.kind]}：{node.name}{node.provenance?.version ? ` · v${node.provenance.version}` : ''}{node.people_run_id ? ` · 人员版本 ${node.people_run_id}` : ''}</p>)}
      {detail.freshness && (['changed', 'unavailable'].includes(detail.freshness.investigation) || ['changed', 'unavailable'].includes(detail.freshness.people_materials) || detail.freshness.newer_people_version) && <p className="text-xs text-orange-700">当前来源已变化或无法核对；以下仍为所选版本的冻结内容。</p>}
      {detail.target.provenance?.event_id && <Link className="text-blue-600 underline" to={`/investigation?task_id=${encodeURIComponent(taskId)}&event=${encodeURIComponent(detail.target.provenance.event_id)}`}>在调查工作台查看此事件</Link>}
      {detail.target.provenance?.version && <p className="text-xs">准确版本：v{detail.target.provenance.version}</p>}
      {detail.target.provenance?.review_state && <p className="text-xs">分析复核状态：{detail.target.provenance.review_state === 'accepted' ? '已接受' : '待复核'}</p>}
      {detail.target.provenance?.claim_type && <p className="text-xs">结论性质：{{ FACT: '事实性陈述', INFERENCE: '推断', HYPOTHESIS: '假设' }[detail.target.provenance.claim_type] || detail.target.provenance.claim_type} · 引用状态：{detail.target.provenance.grounding_status}（引用有效不等于结论已被证实）</p>}
      {detail.target.summary && <p className="whitespace-pre-wrap text-sm">{detail.target.summary}</p>}
      {detail.target.reason && <p className="whitespace-pre-wrap text-sm">依据及限制：{detail.target.reason}</p>}
      {detail.target.status === 'machine_suggestion' && <p className="text-sm text-purple-600">机器建议 · 待核查，尚未改变调查事件、审核结论或报告。</p>}
      {(detail.target.refs || []).map((ref, i) => <blockquote key={`${ref.source_id}:${i}`} className="border-l-2 border-purple-400 pl-3 text-sm"><p>{ref.quote}</p><p className="text-xs text-slate-500">来源：{ref.source_id} · 片段字符位置 {ref.start} · 快照 {ref.snapshot_hash}</p></blockquote>)}
      <p className="text-xs text-slate-500">来源版本：{detail.source_version}</p>
      {detail.sources.length === 0 && <p className="text-sm">该节点当前没有可回查的关联材料；不能据此判断没有活动或关系。</p>}
      {detail.sources.map(source => <details key={source.id} className="rounded-lg bg-slate-100 p-3 dark:bg-slate-800" open={detail.sources.length === 1}>
        <summary className="cursor-pointer text-sm">{source.name || source.evidence_key} · {sourceNames[source.kind] || source.kind}</summary>
        <div className="mt-2 space-y-2 text-xs">
          <p>证据标识：{source.evidence_key}</p><p>快照哈希：{source.snapshot_hash}</p><p>文本哈希：{source.text_hash}</p>
          {source.people_run_id && <p>人员版本：{source.people_run_id} · 提及标识：{source.mention_id} · 材料字节版本{source.binding_verified ? '已匹配' : '未核对'}</p>}
          {(source.text_truncated || source.payload_truncated) && <p className="text-orange-700">来源文本或快照展示有截断，请结合原来源核查。</p>}
          <p className="whitespace-pre-wrap">{source.text || '该快照无可引用的正文或分析摘要。'}</p>
          {source.payload && <details><summary>冻结快照字段（时间字段不等于行为发生时间）</summary><pre className="whitespace-pre-wrap break-all">{JSON.stringify(source.payload, null, 2)}</pre></details>}
        </div>
      </details>)}
    </div>}
  </section>;
}
