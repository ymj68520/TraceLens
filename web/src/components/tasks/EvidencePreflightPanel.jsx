import { forensicLabel } from '../../utils/forensicLabels';
import { useEffect, useState } from 'react';
import Button from '../common/Button';
import { FIELD_AUTH_ENABLED } from '../../config/runtime';
import { openFieldResource } from '../../services/fieldResource';
import {
  cancelEvidencePreflight,
  evidenceManifestUrl,
  getEvidencePreflight,
  listEvidenceCandidates,
  startEvidencePreflight,
} from '../../services/evidenceIntakeService';

const textError = (error) => error?.data?.detail || error?.message || '预检请求失败';
const kindLabel = {
  aliyun_raw_export: '阿里云 RAW 系统盘导出包',
  derived_html_report: '第三方派生报告', miui_backup: 'MIUI 备份',
  harmony_decrypted_backup: '已解密的鸿蒙备份',
  android_backup: '安卓备份', android_backup_encrypted: '已加密 安卓备份',
  android_backup_unsupported: '不支持的 安卓备份 变体',
  android_logical_tree: 'Android 逻辑提取目录', android_logical_zip: 'Android 逻辑提取 ZIP',
  zip_container: 'ZIP 容器', zip_container_unsafe: 'ZIP 包含危险路径或链接',
  seven_zip_container: '7z 容器',
  sqlite_database: 'SQLite 数据库', android_sparse_image: 'Android sparse 镜像',
  ewf_candidate: 'E01/EWF 候选', raw_image_candidate: '原始镜像候选',
  vendor_container_unknown: '厂商案例容器（未支持解析）', unknown_directory: '未知目录',
  unknown_file: '未知文件', tar_container: 'TAR 容器',
  android_sparse_userdata: 'Android sparse userdata',
  android_raw_super: 'Android raw super',
  android_sparse_super: 'Android sparse super',
  android_full_disk_super: '完整镜像中的 super 分区',
};
const stateLabel = {
  queued: '排队中', running: '检查中', completed: '预检完成',
  partial: '部分完成', cancelled: '已取消', interrupted: '服务中断', failed: '失败',
};
const integrityLabel = {
  verified: '来源哈希已计算', not_calculated: '未计算完整哈希', incomplete: '完整性未完成',
  manifest_hashed: '逐文件哈希已计算（非目录快照）',
};
const adapterLabel = {
  'aliyun-image': '阿里云系统盘校验解包与 Linux 分析',
  android_report: '第三方报告只读索引', 'miui-backup': 'MIUI 备份解析',
  'oppo-backup': 'OPPO 雷电快取解析',
  dir: 'Android 目录解析', zip: 'Android ZIP 解析',
  sqlite_inventory: 'SQLite 清单', tsk_probe_required: '需验证镜像及文件系统',
  tar: 'Android TAR 按需提取', 'seven-zip': 'Android 7z 按需提取',
  'android-backup': '安卓备份 按需提取',
  'filesystem-image': 'Android EXT4/F2FS 镜像只读分析',
  'android-container': 'AOSP sparse / LP 规范化',
};
const archiveWarningLabel = {
  archive_path_escape: '归档含越界路径', archive_symlink: '归档含符号链接',
  encrypted_entries: '归档含加密成员', extreme_compression_ratio: '压缩比异常',
};

export default function EvidencePreflightPanel({ onCreateTask }) {
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState('');
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [password, setPassword] = useState('');
  const [verifiedPassword, setVerifiedPassword] = useState('');
  const [selectedSlot, setSelectedSlot] = useState(0);

  useEffect(() => {
    let active = true;
    listEvidenceCandidates().then((result) => {
      if (!active) return;
      setCandidates(result.candidates || []);
      setSelected((current) => current || result.candidates?.[0]?.id || '');
    }).catch((err) => { if (active) setError(textError(err)); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!job?.id || !['queued', 'running'].includes(job.status)) return undefined;
    let active = true;
    const timer = setInterval(() => {
      getEvidencePreflight(job.id).then((result) => {
        if (active) setJob((current) => current?.id === result.job.id ? result.job : current);
      }).catch((err) => { if (active) setError(textError(err)); });
    }, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [job?.id, job?.status]);

  const run = async (fullHash) => {
    if (!selected) return;
    setBusy(true);
    setError('');
    setJob(null);
    setVerifiedPassword('');
    try {
      const passwordForJob = ['android_backup_encrypted', 'seven_zip_container'].includes(selectedCandidate?.kind)
        ? password : '';
      const result = selectedSlot
        ? await startEvidencePreflight(selected, fullHash, passwordForJob, selectedSlot)
        : passwordForJob
          ? await startEvidencePreflight(selected, fullHash, passwordForJob)
          : await startEvidencePreflight(selected, fullHash);
      setJob(result.job);
      setVerifiedPassword(passwordForJob);
    } catch (err) {
      setError(textError(err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!job?.id) return;
    try {
      const result = await cancelEvidencePreflight(job.id);
      setJob(result.job);
    } catch (err) {
      setError(textError(err));
    }
  };

  const selectedCandidate = candidates.find((item) => item.id === selected);
  return <section className="space-y-4 rounded-2xl border border-indigo-200 bg-white p-5 dark:border-indigo-900 dark:bg-slate-800" data-testid="evidence-preflight-panel">
    <div><h2 className="text-lg font-semibold text-slate-900 dark:text-white">未知检材预检</h2>
      <p className="mt-1 text-sm text-slate-500">仅识别格式、枚举有限清单与校验哈希；不会解压、执行或修改检材。预检完成不等于取证或分析完成。</p></div>
    <label className="block text-sm font-medium">服务器证据目录中的候选检材
      <select aria-label="候选检材" value={selected} onChange={(event) => { setSelected(event.target.value); setSelectedSlot(0); setJob(null); }} className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900">
        {!candidates.length && <option value="">未发现候选检材</option>}
        {candidates.map((item) => <option key={item.id} value={item.id}>{item.name} · {kindLabel[item.kind] || forensicLabel(item.kind)}</option>)}
      </select>
    </label>
    <p className="text-xs text-slate-500">默认查找项目上级目录；可通过 TRACELENS_EVIDENCE_INBOX 指定只读证据目录。文件名与扩展名仅用于候选判断。</p>
    {['android_backup_encrypted', 'seven_zip_container'].includes(selectedCandidate?.kind) &&
      <label className="block text-xs font-medium">归档/备份密码（仅本次预检，内存中使用，不写入清单）
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
      </label>}
    {['android_sparse_image', 'raw_image_candidate', 'ewf_candidate'].includes(selectedCandidate?.kind) &&
      <label className="block text-xs font-medium">逻辑分区元数据槽（仅表示选择哪个槽，不代表当前启动槽）
        <select aria-label="逻辑分区元数据槽" value={selectedSlot} onChange={(event) => setSelectedSlot(Number(event.target.value))}
          className="mt-1 block rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
          {Array.from({ length: Math.min(job?.container?.super_inventory?.metadata_slot_count || 2, 32) }, (_, i) =>
            <option key={i} value={i}>slot {i}</option>)}
        </select>
      </label>}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={!selected || busy} onClick={() => run(false)}>快速识别</Button>
      <Button size="sm" variant="outline" disabled={!selected || busy} onClick={() => run(true)}>后台计算完整 SHA-256</Button>
      {['queued', 'running'].includes(job?.status) && <Button size="sm" variant="ghost" onClick={cancel}>取消预检</Button>}
    </div>
    {selectedCandidate && <p className="text-xs text-slate-500">初步判断：{kindLabel[selectedCandidate.kind] || forensicLabel(selectedCandidate.kind)} · 置信级别 {forensicLabel(selectedCandidate.confidence)}；尚未分析内容。</p>}
    {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
    {job && <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-900" data-testid="evidence-preflight-result">
      <p className="font-semibold">状态：{stateLabel[job.status] || forensicLabel(job.status)} · 完整性：{integrityLabel[job.integrity_status] || '未计算'}</p>
      <p>识别：{kindLabel[job.detected?.kind] || forensicLabel(job.detected?.kind, '正在识别')}；适配器：{adapterLabel[job.detected?.adapter] || '无，需现场确认'}</p>
      {job.detected?.encryption_status && <p>加密状态：{forensicLabel(job.detected.encryption_status)}；{job.detected.reason || '需核对备份变体'}</p>}
      <p>已检查文件：{Number(job.file_count || 0).toLocaleString()}；已读取：{Number(job.bytes_read || 0).toLocaleString()} 字节</p>
      {job.sha256 && <p className="break-all font-mono text-xs">源文件 SHA-256：{job.sha256}</p>}
      {job.tree_manifest_sha256 && <p className="break-all font-mono text-xs">目录文件清单摘要：{job.tree_manifest_sha256}（不是原介质哈希）</p>}
      {job.archive?.warnings?.length > 0 && <p className="text-amber-700">归档警告：{job.archive.warnings.map((code) => archiveWarningLabel[code] || code).join('、')}</p>}
      {job.archive?.reason && <p className="text-amber-700">归档清单未展开：{job.archive.reason}</p>}
      {job.archive && ['tar_container', 'seven_zip_container', 'android_backup'].includes(job.detected?.kind) &&
        <div className="rounded-lg border border-slate-200 p-2 text-xs">
          <p>归档成员：{job.archive.entries ?? '未完成枚举'} · Android 根路径：{job.archive.root_mapping || '未证实'} · 加密：{forensicLabel(job.archive.encryption_status)}</p>
          <p>规范化状态：{forensicLabel(job.detected?.analysis_state, '尚未就绪')} · 可用于 Android 分析：{job.archive.ready && job.detected?.adapter ? '是（仍需 任务验证）' : '否'}</p>
          {!!job.archive.skipped_links && <p className="text-amber-700">跳过链接成员：{job.archive.skipped_links}</p>}
          {!!job.archive.nested_container_detected && <p className="text-amber-700">发现嵌套容器：{job.archive.nested_container_detected}（未递归解析）</p>}
        </div>}
      {!!job.nested_candidates?.length && <details className="text-xs"><summary className="cursor-pointer font-semibold">嵌套镜像/容器候选（仅按后缀，未验证格式）· {job.nested_candidates.length}</summary><ul className="mt-1 space-y-1">{job.nested_candidates.map((path) => <li key={path} className="break-all font-mono">{path}</li>)}</ul></details>}
      {!!Object.keys(job.extension_counts || {}).length && <p className="text-xs text-slate-500">已检查文件后缀：{Object.entries(job.extension_counts).slice(0, 10).map(([suffix, count]) => `${suffix} ${count}`).join(' · ')}</p>}
      {job.inventory_truncated && <p className="font-semibold text-amber-700">清单达到时间或数量上限，结果不完整。{job.limit_reason}</p>}
      {job.error && <p className="text-rose-700">{job.error}</p>}
      {job.manifest_available && <a href={evidenceManifestUrl(job.id)} onClick={(event) => {
        if (!FIELD_AUTH_ENABLED) return;
        event.preventDefault();
        openFieldResource(evidenceManifestUrl(job.id), { downloadName: 'evidence-manifest.jsonl' })
          .catch((err) => setError(err.message));
      }} className="text-primary-600 hover:underline">下载只读检材清单</a>}
      {job.image && <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs dark:border-indigo-900 dark:bg-slate-900">
        <p>镜像探测：{job.image.reason} · 分区 {job.image.android_candidates?.length || 0} · 读取器 {job.image.reader || '不可用'}</p>
        {job.image.selected_partition && <p>选中：{job.image.selected_partition.kind} @ {job.image.selected_partition.base} · 加密状态 {forensicLabel(job.image.selected_partition.encryption?.state)}</p>}
        {!job.image.ready && <p className="text-amber-700">{job.image.selected_partition?.locked ? '用户数据已识别但被锁定；可以建立只读覆盖任务，不会尝试解析密文。' : '未确认可读 Android userdata；不会创建已验证镜像任务。'}</p>}
      </div>}
      {job.container && <div className="rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs dark:border-violet-900 dark:bg-slate-900">
        <p className="font-semibold">Android 容器：{forensicLabel(job.container.kind)} · {job.container.reason || (job.container.ready ? '可进入规范化任务' : '尚未就绪')}</p>
        {job.container.sparse && <p>sparse 结构：{forensicLabel(job.container.sparse.validation_status)} · 展开后 {Number(job.container.sparse.expanded_size || 0).toLocaleString()} 字节 · {job.container.sparse.chunk_count || 0} 个数据块</p>}
        {job.container.userdata_preflight?.selected_partition && <p>规范化后 userdata：{String(job.container.userdata_preflight.selected_partition.kind).toUpperCase()} · 任务分析前仍需重新转换与验哈希</p>}
        {job.container.super_inventory && <>
          <p>逻辑分区元数据 {job.container.super_inventory.metadata_version?.join('.')} · 槽 {job.container.selected_slot}（活动槽未知）· 逻辑分区 {job.container.super_inventory.partition_count}</p>
          <p>仅规范化系统分区；用户数据分区：来源中未包含。不能据此声称用户数据已分析。</p>
          <ul>{job.container.super_inventory.partitions?.map((partition) => <li key={partition.name}>{partition.name} · {Number(partition.size).toLocaleString()} 字节 · {partition.group_name}</li>)}</ul>
        </>}
        {job.container.warnings?.length > 0 && <p className="text-amber-700">警告：{job.container.warnings.join('、')}</p>}
      </div>}
      {job.aliyun_image && <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-900">
        <p className="font-semibold">阿里云 Linux 系统盘导出包</p>
        <p className="break-all">包内 RAW：{job.aliyun_image.member_name}</p>
        <p>展开大小：{(Number(job.aliyun_image.raw_size) / 1024 ** 3).toFixed(2)} GiB</p>
        <p>已检查头部；完整容器、gzip 校验和、唯一 RAW 与来源哈希在任务解包阶段再次验证。请预留展开大小及分析结果所需空间。</p>
      </div>}
      {job.status === 'completed' && ['verified', 'manifest_hashed'].includes(job.integrity_status) &&
        ['dir', 'zip', 'miui-backup', 'harmony-backup', 'oppo-backup', 'tar', 'seven-zip', 'android-backup', 'filesystem-image', 'android-container', 'aliyun-image'].includes(job.detected?.adapter) &&
        (!['tar', 'seven-zip', 'android-backup', 'filesystem-image', 'android-container', 'aliyun-image'].includes(job.detected?.adapter) ||
          (job.integrity_status === 'verified' && (job.archive?.inspected && job.archive?.ready || job.image?.ready || job.image?.selected_partition?.locked || job.container?.ready || job.aliyun_image?.ready))) &&
        (job.detected?.adapter !== 'android-container' || selectedSlot === job.selected_slot) &&
        (job.detected?.kind !== 'android_backup_encrypted' || verifiedPassword) && onCreateTask &&
        <div><Button size="sm" onClick={() => {
          onCreateTask({
          image_path: job.source_path, android_source: job.detected.adapter,
          ...(job.detected.adapter === 'aliyun-image' ? { scenarios: ['linux'], platform_analyze: true } : {}),
          ...(['tar', 'seven-zip', 'android-backup', 'filesystem-image', 'android-container', 'aliyun-image'].includes(job.detected.adapter) ? {
            preflight_job_id: job.id, preflight_source_sha256: job.sha256,
            preflight_detected_kind: job.detected.kind,
          } : {}),
          ...(job.detected.adapter === 'android-container' ? {
            preflight_plan_sha256: job.container.plan_sha256,
            preflight_selected_slot: selectedSlot,
          } : {}),
          ...(verifiedPassword ? { backup_password: verifiedPassword } : {}),
          });
          setPassword('');
          setVerifiedPassword('');
        }}>{job.detected.adapter === 'aliyun-image' ? '按此来源新建阿里云分析任务' : job.detected.adapter === 'android-container' && job.container?.super_inventory
            ? '建立系统分区规范化任务' : '按此来源新建 安卓分析任务'}</Button>
          <p className="mt-1 text-xs text-slate-500">仅预填来源与类型；创建前仍须确认案情和检材状态，预检哈希并不代替解析核验。</p>
        </div>}
    </div>}
  </section>;
}
