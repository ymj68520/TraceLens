import { useEffect, useState } from 'react';
import Card from './common/Card';
import { captureAndroidArtifact, getAndroidArtifact, getAndroidArtifacts } from '../services/evidenceIntakeService';
import { useNavigate } from 'react-router-dom';

const KINDS = [
  ['sms', '短信'], ['contacts', '联系人'], ['apps', '已安装应用'], ['wifi', 'Wi-Fi'],
];

export default function AndroidArtifactsCard({ taskId }) {
  const navigate = useNavigate();
  const [kind, setKind] = useState('sms');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    let active = true;
    setResult(null);
    setDetail(null);
    setError('');
    getAndroidArtifacts(taskId, kind, query, page).then((value) => {
      if (active) setResult(value);
    }).catch((err) => {
      if (active) setError(err?.data?.detail || err?.message || '安卓工件不可用');
    });
    return () => { active = false; };
  }, [taskId, kind, query, page]);

  const showDetail = (id) => {
    setDetail(null);
    getAndroidArtifact(taskId, kind, id).then(setDetail).catch((err) => {
      setError(err?.data?.detail || err?.message || '来源详情不可用');
    });
  };

  const captureSelected = async () => {
    if (!detail || !detail.record_hash || !detail.source_revision) return;
    setCapturing(true); setError('');
    try {
      const captured = await captureAndroidArtifact(taskId, kind, detail.record.id,
        detail.record_hash, detail.source_revision);
      navigate(`/investigation?task_id=${encodeURIComponent(taskId)}&evidence_key=${encodeURIComponent(captured.evidence_key)}`);
    } catch (err) {
      setError(err?.data?.detail || err?.message || '冻结选中记录失败；请刷新后重试');
    } finally { setCapturing(false); }
  };

  return <Card title="AndroidAnalyzer 原生工件" subtitle="此处读取 android.db；第三方 HTML 派生报告仍在独立 records.db。">
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">{KINDS.map(([value, label]) => <button type="button" key={value}
        onClick={() => { setKind(value); setPage(1); }}
        className={`rounded-lg px-3 py-1 text-sm ${kind === value ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700'}`}>{label}</button>)}</div>
      <label className="block text-sm">检索当前类别 <input className="ml-2 rounded-lg border border-slate-300 px-2 py-1" value={query}
        onChange={(event) => { setQuery(event.target.value); setPage(1); }} maxLength={200} /></label>
      {error && <p role="alert" className="rounded-lg bg-amber-50 p-2 text-sm text-amber-800">{error}</p>}
      {result && <>
        <p className="text-sm text-slate-600">共 {result.total} 条 · 第 {page} 页。此列表不能代表检材完整率。</p>
        <ul className="max-h-96 space-y-2 overflow-auto">{result.records.map((item) => <li key={item.id}>
          <button type="button" onClick={() => showDetail(item.id)} className="w-full rounded-lg border border-slate-200 p-2 text-left text-sm hover:border-indigo-400">
            <span className="font-mono text-slate-500">#{item.id}</span> {item.body || item.display_name || item.package_name || item.ssid || '（无摘要）'}
          </button></li>)}</ul>
        <div className="flex gap-2 text-sm"><button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
          <button type="button" disabled={page * result.page_size >= result.total} onClick={() => setPage(page + 1)}>下一页</button></div>
      </>}
      {detail && <section className="rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-sm">
        <h3 className="font-semibold">记录与来源核对</h3>
        <p className="mt-1 text-amber-800">{detail.warning}</p>
        <dl className="mt-2 space-y-1 break-all">{Object.entries(detail.record).map(([key, value]) => <div key={key}><dt className="inline font-medium">{key}：</dt><dd className="inline">{String(value ?? '—')}</dd></div>)}</dl>
        {detail.source && <div className="mt-2 rounded-lg bg-white p-2">
          <p>候选路径：{detail.source.normalized_path}</p><p>原始路径：{detail.source.original_path || '未记录'}</p>
          <p>文件 SHA-256：{detail.source.sha256 || '未记录'}</p>
          <p>分区：{detail.source.partition_name || '未记录'} · 偏移：{detail.source.partition_start_offset ?? '未记录'}</p>
          <p>原始表/主键：未逐条记录 · WAL frame：未逐条验证</p>
        </div>}
        {!detail.source && <p className="mt-2">无法把本条结果唯一关联到某个来源文件。</p>}
        <button type="button" disabled={capturing} onClick={captureSelected}
          className="mt-3 rounded-lg bg-indigo-600 px-3 py-2 font-medium text-white disabled:opacity-50">
          {capturing ? '正在冻结…' : '将此单条记录加入调查研判'}
        </button>
        <p className="mt-1 text-xs text-slate-600">将冻结当前 AndroidAnalyzer 派生结果版本；不会把整部手机或同类其他记录加入报告。</p>
      </section>}
    </div>
  </Card>;
}
