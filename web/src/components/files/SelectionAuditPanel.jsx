import { useEffect, useState } from 'react';
import api from '../../services/api';

const families = { business: '用户文档与业务配置', activity: '操作与系统活动', program: '程序与持久化配置', browser: '浏览与通信数据库', media: '媒体资料', other: '其他来源' };
const states = { unprobed: '未完成探测', signature_confirmed: '已识别格式签名', readable: '可读文本', ok: '解析成功', partial: '部分可读', metadata_only: '仅元数据', empty: '空内容', error: '解析失败', source_error: '来源读取失败', unsupported: '未支持' };

export default function SelectionAuditPanel({ taskId, running = false }) {
  const [plan, setPlan] = useState(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let active = true;
    setPlan(null);
    const refresh = () => taskId && api.get(`/api/forensics/files/selection-plan?task_id=${encodeURIComponent(taskId)}`)
      .then((value) => { if (active) setPlan(value?.plan || null); }).catch(() => { if (active) setPlan(null); });
    refresh();
    const timer = running ? setInterval(refresh, 15000) : null;
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [taskId, running]);
  if (!plan) return null;
  const counts = plan.counts || {}, usage = plan.usage || {};
  return <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm dark:border-slate-700 dark:bg-slate-800" aria-label="候选选择审计">
    <button type="button" onClick={() => setExpanded((value) => !value)} className="font-semibold text-slate-900 dark:text-white">
      候选选择审计 · {counts.selected ?? 0} 个分析代表 {expanded ? '收起' : '展开'}
    </button>
    <p className="mt-2 text-slate-600 dark:text-slate-300">索引 {counts.indexed ?? 0} · 候选 {counts.candidates ?? 0} · 探测尝试 {counts.probed ?? 0} · 零字节 {counts.zero_bytes ?? 0}</p>
    <p className="mt-1 text-xs text-slate-500">模型请求 {usage.used_calls ?? 0}/{usage.max_calls ?? plan.model_budget?.max_calls ?? '—'} · 已预留令牌上界 {usage.reserved_tokens ?? 0}/{usage.max_tokens ?? plan.model_budget?.max_tokens ?? '—'}。重试计入预算；未选中不等于不相关。</p>
    <p className="mt-1 text-xs text-slate-500">已完成 {plan.execution?.completed ?? 0} · 失败 {plan.execution?.failed ?? 0} · 其余为尚未完成。选择计划完成不表示所有来源均已研判。</p>
    <p className="mt-1 text-xs text-slate-500">当前计划：{plan.plan_id}。本面板只统计此计划，历史运行不累加。</p>
    {plan.quality && <div className="mt-2 text-xs" aria-label="来源处理质量">
      <p>{plan.quality.label} · 可读 {plan.quality.counts.readable} · 有效零记录 {plan.quality.counts.zero_records} · 仅元数据 {plan.quality.counts.metadata_only} · 未支持 {plan.quality.counts.unsupported} · 解析失败 {plan.quality.counts.parse_failed} · 模型失败 {plan.quality.counts.model_failed} · 未探测 {plan.quality.counts.unprobed} · 未处理 {plan.quality.counts.unprocessed}</p>
      <p>{plan.quality.scope}</p>
    </div>}
    {expanded && <>
      <div className="mt-3 flex flex-wrap gap-3">{Object.entries(plan.family_counts || {}).map(([key, count]) => <span key={key}>{families[key] || '其他类别'}：{count}</span>)}</div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">{Object.entries(plan.probe_states || {}).map(([key, count]) => <span key={key}>{states[key] || '状态待核对'}：{count}</span>)}</div>
      <p className="mt-2 text-xs text-slate-500">下列为最多 50 条审计预览；完整计划保存在任务数据库。相同内容来源仍保留，代表分析不表示每份来源均已独立研判。</p>
      <ul className="mt-3 max-h-64 space-y-2 overflow-auto">{(plan.display_candidates || []).map((item) => <li key={`${item.task_id}:${item.source_id}:${item.path}`}>
        <div className="break-all font-mono text-xs">{item.path}</div>
        <div className="text-xs text-slate-500">{item.selected ? '已选' : '未选'} · {states[item.probe_state] || '状态待核对'} · {item.reason || '等待记录选择原因'}</div>
        {item.score != null && <div className="text-xs text-slate-400">排序分 {item.score} · 同组多样性调整 {item.diversity_penalty ?? 0}；用于安排读取顺序，不代表违法判断。</div>}
      </li>)}</ul>
    </>}
  </section>;
}
