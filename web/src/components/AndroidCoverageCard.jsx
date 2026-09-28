import { useEffect, useState } from 'react';
import Card from './common/Card';
import { getAndroidSourceCoverage, androidCoverageManifestUrl, androidNormalizationManifestUrl } from '../services/evidenceIntakeService';
import { FIELD_AUTH_ENABLED } from '../config/runtime';
import { openFieldResource } from '../services/fieldResource';

const statusLabel = {
  parsed: '已完成对应解析器', staged_for_parser: '已提取，解析结果待核对',
  no_candidate_path: '未找到候选文件', not_found_or_unreadable: '未找到或无法读取',
  extract_failed: '提取失败', locked_or_unsupported: '加密或格式不支持',
  LOCKED: '加密锁定', UNSUPPORTED: '格式暂不支持', PARSED: '已解析', FOUND: '已发现',
  NOT_PRESENT_IN_SOURCE: '该来源不含 userdata',
};

export default function AndroidCoverageCard({ taskId }) {
  const [coverage, setCoverage] = useState(null);
  const [error, setError] = useState('');
  const download = (event, url, name) => {
    if (!FIELD_AUTH_ENABLED) return;
    event.preventDefault();
    openFieldResource(url, { downloadName: name }).catch((err) => setError(err.message));
  };

  useEffect(() => {
    let active = true;
    setCoverage(null);
    setError('');
    getAndroidSourceCoverage(taskId).then((result) => {
      if (active) setCoverage(result.coverage);
    }).catch((err) => {
      if (active) setError(err?.data?.detail || err?.message || '来源覆盖记录不可用');
    });
    return () => { active = false; };
  }, [taskId]);

  return <Card title="安卓来源覆盖与解析状态" subtitle="任务完成进度不等于原始检材已全部解析。" data-testid="android-coverage-card">
    {!coverage && !error && <p className="text-sm text-slate-500">正在读取来源覆盖情况…</p>}
    {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
    {coverage && <div className="space-y-3">
      {coverage.warnings.map((warning) => <p key={warning} className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">{warning}</p>)}
      {!coverage.available && <p className="text-sm text-slate-500">该任务没有可读取的安卓分析数据库。</p>}
      {coverage.available && <>
        {coverage.normalization_manifest && <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs text-violet-900">
          <p className="font-semibold">AOSP 容器规范化 · {coverage.normalization_manifest.kind}</p>
          <p>metadata slot {coverage.normalization_manifest.selected_slot} · 活动槽未知 · userdata：{coverage.normalization_manifest.userdata?.status}</p>
          {coverage.normalization_manifest.partition_provenance?.length > 0 && <ul className="mt-1 space-y-1">{coverage.normalization_manifest.partition_provenance.map((item) =>
            <li key={item.logical_partition_name}>{item.logical_partition_name} · {item.filesystem_type === 'EROFS' || item.filesystem_type === 'UNKNOWN' ? 'UNSUPPORTED_FILESYSTEM' : item.filesystem_type} · SHA-256 {item.derived_partition_sha256?.slice(0, 16)}…</li>)}</ul>}
          <a className="mt-2 inline-block font-semibold text-violet-700 underline" href={androidNormalizationManifestUrl(taskId)} onClick={(event) => download(event, androidNormalizationManifestUrl(taskId), 'android-normalization-manifest.json')}>下载完整规范化来源链</a>
        </div>}
        {coverage.manifest && <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-900">
          <p className="font-semibold">镜像覆盖清单 · {coverage.manifest.filesystem} / {coverage.manifest.encryption}</p>
          <p>容器：{coverage.manifest.container} · 分区偏移：{coverage.manifest.partition?.offset || '0'} · 读取器：{coverage.manifest.reader}</p>
          <p className="break-all">引用：android_coverage_manifest.json · 来源 SHA-256：{coverage.manifest.source_image_sha256 || '未验证'}</p>
          <a className="font-semibold text-indigo-700 underline" href={androidCoverageManifestUrl(taskId)} onClick={(event) => download(event, androidCoverageManifestUrl(taskId), 'android-coverage-manifest.json')}>下载本报告引用的覆盖清单</a>
          <p>各类工件：{Object.entries(coverage.manifest.artifact_types || {}).map(([kind, item]) => `${kind} ${item.status} ${item.parsed_count}`).join(' · ')}</p>
          {coverage.manifest.userdata?.status === 'NOT_PRESENT_IN_SOURCE' && <p className="font-semibold text-amber-800">super 来源不包含 userdata；本任务未分析短信、联系人等用户数据。</p>}
        </div>}
        <div className="flex flex-wrap gap-2">{Object.entries(coverage.artifact_counts).map(([name, count]) => <span key={name} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">{name}: {Number(count).toLocaleString()}</span>)}</div>
        {!!coverage.sources.length && <div className="max-h-60 space-y-2 overflow-auto">{coverage.sources.map((item) => <div key={`${item.artifact_kind}:${item.source_path}`} className="rounded-lg border border-slate-200 p-2 text-xs">
          <p className="font-semibold">{item.artifact_kind} · {statusLabel[item.status] || item.status}</p>
          <p className="mt-1 break-all font-mono text-slate-500">{item.source_path}</p>
          {item.detail && <p className="mt-1 text-slate-500">{item.detail}</p>}
        </div>)}</div>}
      </>}
      <p className="text-xs text-slate-500">未找到文件不能证明数据不存在；已提取也不证明表内记录全部解析成功。重要结论仍需回查原文件。</p>
      <p className="text-xs text-slate-500">PARSED / FOUND / NOT_FOUND 统计的是预设候选来源的状态，不是 Android 全部工件的分母；FOUND 与 PARSED 不能当成独立工件数相加。这里不计算“取证完整率”。</p>
    </div>}
  </Card>;
}
