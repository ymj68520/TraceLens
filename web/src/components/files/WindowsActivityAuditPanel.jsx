import { useEffect, useState } from 'react';
import api from '../../services/api';

const names = { event_logs: '事件日志', prefetch_files: '程序运行记录', browser_history: '浏览历史', browser_downloads: '下载记录', browser_logins: '账户条目', windows_services: '服务配置', scheduled_tasks: '计划任务配置', usb_devices: 'USB记录', recycle_bin: '回收站', amcache_entries: '程序缓存元数据' };
const states = { ok: '已导入', empty: '有效空表', missing_table: '缺少来源表', incompatible_schema: '来源结构不兼容', partial: '部分可用' };
export default function WindowsActivityAuditPanel({ taskId, running = false }) {
  const [coverage, setCoverage] = useState(null);
  useEffect(() => {
    let active = true;
    const refresh = () => taskId && api.get(`/api/llm/windows-activity/${encodeURIComponent(taskId)}`)
      .then(value => { if (active) setCoverage(value?.coverage || null); }).catch(() => { if (active) setCoverage(null); });
    setCoverage(null); refresh();
    const timer = running ? setInterval(refresh, 15000) : null;
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [taskId, running]);
  if (!coverage) return null;
  return <details className="rounded-lg border border-slate-200 bg-white p-4 text-sm dark:border-slate-700 dark:bg-slate-800" aria-label="Windows活动覆盖">
    <summary className="font-semibold">Windows活动覆盖 · {coverage.success === false ? '导入失败，当前时间线未更新' : coverage.complete ? '已导入' : '部分可用，请核对限制'}</summary>
    <p className="mt-2">有时间记录 {coverage.valid_records || 0} · 无时间观察 {coverage.undated_records || 0} · 解析失败 {coverage.failed_records || 0}</p>
    <p className="mt-2 text-xs text-slate-500">服务和计划任务配置不等于实际执行。未知时间不填当前时间；回收日志与标准记录分别标识。历史来源版本保留。</p>
    <ul className="mt-3 space-y-1">{Object.entries(coverage.tables || {}).map(([kind, value]) => <li key={kind}>
      {names[kind] || '其他来源'}：{states[value.status] || '待核对'}；输入 {value.input}，时间线活动 {value.timeline_events}，无时间 {value.undated}，部分可读 {value.partial || 0}，仅元数据/跳过 {value.ignored || 0}，失败 {value.failed}
    </li>)}</ul>
    <p className="mt-2 break-all text-xs text-slate-500">结果版本：{coverage.result_set_id}</p>
    <ul className="mt-2 text-xs text-slate-500">{(coverage.limitations || []).map(text => <li key={text}>{text}</li>)}</ul>
  </details>;
}
