import { motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Virtuoso } from 'react-virtuoso';
import { Search, Smartphone, Package, HardDrive, Calendar, FolderInput, ShieldCheck, Sparkles, ChevronDown } from 'lucide-react';

import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import {
  getMiuiOverview,
  getMiuiInstalledApps,
  getMiuiDbInventory,
  getMiuiQqntOverview,
  getMiuiQqntArtifacts,
  getMiuiQqntRecords,
  getMiuiWechatOverview,
  getMiuiWechatArtifacts,
  getMiuiWechatRecords,
  getAndroidLlmSummary,
} from '../services/forensicsService';

const formatMsDate = (ms) => {
  if (!ms) return '-';
  try {
    return new Date(Number(ms)).toLocaleString();
  } catch {
    return String(ms);
  }
};

const formatSecondsDate = (seconds) => {
  if (!seconds) return '-';
  try {
    return new Date(Number(seconds) * 1000).toLocaleString();
  } catch {
    return String(seconds);
  }
};

const formatBytes = (bytes) => {
  const n = Number(bytes);
  if (!n || n < 0) return '-';
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(2)} KB`;
  return `${n} B`;
};

const bakTypeLabel = (type) => (type === 1 ? '系统应用' : type === 2 ? '用户应用' : '未知');

const openStatusBadge = (status) => {
  if (status === 'decrypted' || status === 'parsed') return { variant: 'green', label: status === 'parsed' ? '已解析' : '已解密' };
  if (status === 'parse_error') return { variant: 'red', label: '解析失败' };
  if (status === 'incomplete_limit' || status === 'limit_exceeded') return { variant: 'yellow', label: '截断(超限)' };
  if (status === 'recognized') return { variant: 'blue', label: '已识别' };
  if (status === 'encrypted_locked') return { variant: 'yellow', label: '已发现但未解密' };
  if (status === 'not_found') return { variant: 'gray', label: '未发现微信主库' };
  if (status === 'unsupported') return { variant: 'gray', label: '待解码' };
  return { variant: 'gray', label: status || '未知' };
};

const STATUS_BAR = {
  decrypted: { bg: 'bg-emerald-500', label: '已解密' },
  parse_error: { bg: 'bg-rose-500', label: '解析失败' },
  incomplete_limit: { bg: 'bg-amber-500', label: '截断(超限)' },
};

const Android = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [apps, setApps] = useState(null);
  const [dbInventory, setDbInventory] = useState(null);
  const [qqntOverview, setQqntOverview] = useState(null);
  const [wechatOverview, setWechatOverview] = useState(null);
  const currentTask = tasks.find((task) => task.id === taskId);

  useEffect(() => {
    if (!taskId) return;
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setOverview(null);
      setApps(null);
      setDbInventory(null);
      setQqntOverview(null);
      setWechatOverview(null);
      try {
        const [ov, ap, inv, qqnt, wx] = await Promise.allSettled([
          getMiuiOverview(taskId),
          getMiuiInstalledApps(taskId),
          getMiuiDbInventory(taskId),
          getMiuiQqntOverview(taskId),
          getMiuiWechatOverview(taskId),
        ]);
        if (ov.status === 'fulfilled') setOverview(ov.value);
        if (ap.status === 'fulfilled') setApps(ap.value);
        if (inv.status === 'fulfilled') setDbInventory(inv.value);
        if (qqnt.status === 'fulfilled') setQqntOverview(qqnt.value);
        if (wx.status === 'fulfilled') setWechatOverview(wx.value);
        if (![ov, ap, inv, qqnt, wx].some((result) => result.status === 'fulfilled' && result.value)) {
          setError('未找到 MIUI 备份数据。请确认该任务使用了 MIUI 备份来源（android_source=miui-backup）。');
        }
      } catch (err) {
        console.error('Failed to fetch MIUI backup data:', err);
        setError(err.message || '加载 MIUI 备份数据失败');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [taskId]);

  if (!taskId) {
    return (
      <div className="space-y-6">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900">MIUI 备份分析</motion.h1>
          <p className="mt-2 text-slate-600">解析小米 MIUI 离线备份（descript.xml + .bak），还原设备信息、应用与 QQNT/微信证据</p>
        </div>
        <Card title="选择任务">
          <p className="text-slate-500">请从 <a href="/tasks" className="text-primary-600 hover:text-blue-800">任务页面</a> 选择一个已完成 MIUI 备份分析的任务，或使用顶部任务选择器。</p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900">MIUI 备份分析</motion.h1>
          <p className="mt-2 text-slate-600">任务: {currentTask?.image_path || taskId}</p>
        </div>
        <Card><div className="flex items-center justify-center h-64"><Spinner size="lg" /><span className="ml-4 text-slate-600">加载 MIUI 备份数据...</span></div></Card>
      </div>
    );
  }

  const manifest = overview?.manifest || {};
  const decryptionStatus = overview?.decryption_status || [];
  const appsList = apps?.apps || [];
  const bakTypeSummary = apps?.bak_type_summary || [];
  const inventory = dbInventory?.inventory || [];
  const packageSummary = dbInventory?.package_summary || [];
  const qqntArtifacts = qqntOverview?.artifact_categories || [];
  const wechatArtifacts = wechatOverview?.artifact_categories || [];
  const wechatSummary = overview?.wechat_summary || {};
  const hasWechatData = Boolean(
    wechatSummary.available ||
    wechatSummary.status === 'parsed' ||
    Number(wechatSummary.messages) > 0 ||
    Number(wechatSummary.contacts) > 0 ||
    Number(wechatSummary.chatrooms) > 0 ||
    Number(wechatSummary.owners) > 0
  );
  const tabData = {
    overview: Object.keys(manifest).length > 0,
    apps: appsList.length > 0,
    inventory: inventory.length > 0,
    qqnt: qqntArtifacts.length > 0,
    wechat: wechatArtifacts.length > 0,
  };

  return (
    <div className="space-y-6">
      <div>
        <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900">MIUI 备份分析</motion.h1>
        <p className="mt-2 text-slate-600">任务: {currentTask?.image_path || taskId}</p>
        {currentTask && <div className="mt-2 flex items-center gap-2 flex-wrap"><Badge variant="blue">{currentTask.status}</Badge>{manifest.device && <Badge variant="purple">{manifest.device}</Badge>}{manifest.miui_version && <Badge variant="gray">{manifest.miui_version}</Badge>}</div>}
      </div>
      {error && <Card title="错误"><div className="p-4 bg-red-50 border border-red-200 rounded-xl"><p className="text-red-800">{error}</p></div></Card>}
      <div className="border-b border-slate-200 overflow-x-auto">
        <nav className="-mb-px flex space-x-8 min-w-max" aria-label="Tabs">
          {[
            { id: 'overview', label: '📦 备份概览', hasData: tabData.overview },
            { id: 'apps', label: '📱 已备份应用', hasData: tabData.apps },
            { id: 'inventory', label: '🗄️ 应用数据库清单', hasData: tabData.inventory },
            { id: 'qqnt', label: '💬 QQNT 证据', hasData: tabData.qqnt },
            { id: 'wechat', label: '🟢 微信证据', hasData: tabData.wechat },
          ].map((tab) => <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={`${activeTab === tab.id ? 'border-blue-500 text-primary-600' : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'} whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}>{tab.label}{!tab.hasData && <span className="ml-1 text-xs text-slate-400">(无数据)</span>}</button>)}
        </nav>
      </div>
      {activeTab === 'overview' && <div className="space-y-6"><OverviewTab taskId={taskId} manifest={manifest} decryptionStatus={decryptionStatus} wechatSummary={wechatSummary} hasWechatData={hasWechatData} /><LlmCoverageCard taskId={taskId} /></div>}
      {activeTab === 'apps' && <AppsTab apps={appsList} bakTypeSummary={bakTypeSummary} />}
      {activeTab === 'inventory' && <InventoryTab inventory={inventory} packageSummary={packageSummary} />}
      {activeTab === 'qqnt' && <QqntEvidenceTab taskId={taskId} overview={qqntOverview} />}
      {activeTab === 'wechat' && <WechatEvidenceTab taskId={taskId} overview={wechatOverview} />}
    </div>
  );
};

const OverviewTab = ({ taskId, manifest, decryptionStatus, wechatSummary, hasWechatData }) => {
  if (Object.keys(manifest).length === 0) return <Card title="备份概览"><p className="text-center py-8 text-slate-500">未找到 MIUI 备份清单</p></Card>;
  const total = decryptionStatus.reduce((sum, item) => sum + Number(item.count || 0), 0);
  const cards = [
    { icon: Smartphone, label: '设备型号', value: manifest.device || '-' },
    { icon: Package, label: 'MIUI 版本', value: manifest.miui_version || '-' },
    { icon: Calendar, label: '备份时间', value: formatMsDate(manifest.backup_date) },
    { icon: HardDrive, label: '备份总大小', value: formatBytes(manifest.total_size) },
    { icon: Package, label: '应用数', value: manifest.package_count ?? '-' },
    { icon: FolderInput, label: '来源文件夹', value: manifest.source_folder || '-' },
  ];
  const wechatStatus = openStatusBadge(wechatSummary.status);
  const wechatStats = [
    { label: '消息', value: wechatSummary.messages },
    { label: '联系人', value: wechatSummary.contacts },
    { label: '群聊', value: wechatSummary.chatrooms },
    { label: '账号', value: wechatSummary.owners },
  ];

  return <Card title="📦 备份概览"><div className="space-y-6"><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{cards.map(({ icon: Icon, label, value }) => <div key={label} className="p-4 bg-slate-50 rounded-xl"><div className="flex items-center gap-2 text-slate-500"><Icon size={16} /><p className="text-sm font-medium">{label}</p></div><p className="mt-1 text-sm text-slate-900 break-all" title={String(value)}>{value}</p></div>)}</div><div><div className="flex items-center gap-2 mb-3"><ShieldCheck size={18} className="text-slate-700" /><h4 className="font-medium text-slate-900">应用数据库解密状态</h4><span className="text-xs text-slate-400">(共 {total} 条)</span></div>{total > 0 ? <><div className="flex h-6 w-full overflow-hidden rounded-lg bg-slate-100">{decryptionStatus.map((item) => { const cfg = STATUS_BAR[item.open_status] || { bg: 'bg-slate-400', label: item.open_status }; return <div key={item.open_status} className={cfg.bg} style={{ width: `${(Number(item.count) / total) * 100}%` }} title={`${cfg.label}: ${item.count}`} />; })}</div><div className="flex flex-wrap gap-4 mt-3">{decryptionStatus.map((item) => { const cfg = STATUS_BAR[item.open_status] || { bg: 'bg-slate-400', label: item.open_status }; return <span key={item.open_status} className="flex items-center gap-2 text-sm text-slate-600"><i className={`w-3 h-3 rounded-sm ${cfg.bg}`} />{cfg.label}: <b>{item.count}</b></span>; })}</div></> : <p className="text-center py-6 text-slate-500">暂无数据库清单数据</p>}</div><div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="flex items-center gap-2"><span className="text-lg">💬</span><h4 className="font-medium text-slate-900">微信关系分析</h4><Badge variant={wechatStatus.variant} size="sm">{wechatStatus.label}</Badge></div><p className="mt-1 text-sm text-slate-600">从本次 MIUI 备份恢复的微信结构化证据</p></div>{hasWechatData ? <Link to={`/wechat-graph?task_id=${encodeURIComponent(taskId)}`} className="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700">打开关系图</Link> : <span className="text-sm text-slate-500">暂无可视化数据</span>}</div><div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">{wechatStats.map(({ label, value }) => <div key={label} className="rounded-lg bg-white/70 p-3 text-center"><p className="text-xl font-semibold text-slate-900">{Number(value || 0).toLocaleString()}</p><p className="text-xs text-slate-600">{label}</p></div>)}</div></div></div></Card>;
};

const AppsTab = ({ apps, bakTypeSummary }) => {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const filtered = useMemo(() => apps.filter((app) => {
    const q = query.trim().toLowerCase();
    return (typeFilter === 'all' || Number(app.bak_type) === Number(typeFilter)) && (!q || (app.package_name || '').toLowerCase().includes(q) || (app.display_name || '').toLowerCase().includes(q));
  }), [apps, query, typeFilter]);
  const typeCounts = useMemo(() => Object.fromEntries(bakTypeSummary.map((item) => [item.bak_type, item.count])), [bakTypeSummary]);
  return <Card title="📱 已备份应用"><div className="space-y-4"><div className="flex flex-wrap gap-3"><SearchInput value={query} onChange={setQuery} placeholder="按包名或显示名搜索..." /><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="px-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200"><option value="all">全部应用 ({apps.length})</option><option value="1">系统应用 ({typeCounts[1] || 0})</option><option value="2">用户应用 ({typeCounts[2] || 0})</option></select></div>{filtered.length === 0 ? <Empty text="没有符合条件的应用" /> : <div className="overflow-x-auto"><table className="min-w-full divide-y divide-slate-200"><thead className="bg-slate-50"><tr><Th>包名</Th><Th>显示名</Th><Th>版本</Th><Th>数据大小</Th><Th>SD 大小</Th><Th>类型</Th></tr></thead><tbody className="bg-white divide-y divide-slate-200">{filtered.slice(0, 200).map((app, index) => <tr key={`${app.package_name}-${index}`} className="hover:bg-slate-50"><td className="px-4 py-3 text-sm text-slate-600 font-mono">{app.package_name}</td><td className="px-4 py-3 text-sm text-slate-900">{app.display_name || '-'}</td><td className="px-4 py-3 text-sm text-slate-600">{app.version_name || app.version_code || '-'}</td><td className="px-4 py-3 text-sm text-slate-600">{formatBytes(app.data_size)}</td><td className="px-4 py-3 text-sm text-slate-600">{formatBytes(app.sd_size)}</td><td className="px-4 py-3"><Badge variant={app.bak_type === 1 ? 'blue' : app.bak_type === 2 ? 'purple' : 'gray'}>{bakTypeLabel(app.bak_type)}</Badge></td></tr>)}</tbody></table>{filtered.length > 200 && <p className="text-center text-xs text-slate-400 py-3">仅显示前 200 条，共 {filtered.length} 条</p>}</div>}</div></Card>;
};

const InventoryTab = ({ inventory, packageSummary }) => {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => { const q = query.trim().toLowerCase(); return q ? inventory.filter((row) => (row.package_name || '').toLowerCase().includes(q)) : inventory; }, [inventory, query]);
  return <Card title="🗄️ 应用数据库清单"><div className="space-y-4"><div className="grid grid-cols-2 md:grid-cols-4 gap-4"><SummaryStat label="涉及应用数" value={packageSummary.length} tone="blue" /><SummaryStat label="数据库文件数" value={packageSummary.reduce((sum, item) => sum + Number(item.db_count || 0), 0)} tone="green" /><SummaryStat label="数据表总数" value={inventory.length} tone="purple" /><SummaryStat label="数据行总数" value={packageSummary.reduce((sum, item) => sum + Number(item.total_rows || 0), 0)} tone="gray" /></div><SearchInput value={query} onChange={setQuery} placeholder="按包名搜索数据库..." />{filtered.length === 0 ? <Empty text="没有数据库清单数据" /> : <div className="border border-slate-200 rounded-xl overflow-hidden"><div className="grid grid-cols-12 gap-2 px-4 py-2 bg-slate-50 text-xs font-medium text-slate-500 uppercase"><div className="col-span-3">包名</div><div className="col-span-3">数据库路径</div><div className="col-span-2">表名</div><div className="col-span-1 text-right">行数</div><div className="col-span-2">列</div><div className="col-span-1 text-center">状态</div></div><Virtuoso data={filtered} style={{ height: '60vh' }} itemContent={(index, row) => { const badge = openStatusBadge(row.open_status); return <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs border-t border-slate-100 hover:bg-slate-50 items-center"><div className="col-span-3 text-slate-600 font-mono truncate" title={row.package_name}>{row.package_name}</div><div className="col-span-3 text-slate-600 font-mono truncate" title={row.db_path}>{row.db_path}</div><div className="col-span-2 text-slate-600 font-mono truncate" title={row.table_name}>{row.table_name || '-'}</div><div className="col-span-1 text-right text-slate-600">{Number(row.row_count || 0).toLocaleString()}</div><div className="col-span-2 text-slate-500 font-mono truncate" title={row.columns}>{row.columns || '-'}</div><div className="col-span-1 text-center"><Badge variant={badge.variant} size="sm">{badge.label}</Badge></div></div>; }} /></div>}</div></Card>;
};

const QqntEvidenceTab = ({ taskId, overview }) => {
  const [artifacts, setArtifacts] = useState([]);
  const [artifactTotal, setArtifactTotal] = useState(0);
  const [records, setRecords] = useState([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [artifactQuery, setArtifactQuery] = useState('');
  const [recordQuery, setRecordQuery] = useState('');
  const [category, setCategory] = useState('');
  const [recordKind, setRecordKind] = useState('kv');
  const [showSensitive, setShowSensitive] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    Promise.all([
      getMiuiQqntArtifacts(taskId, { category, query: artifactQuery, limit: 100 }),
      getMiuiQqntRecords(taskId, { kind: recordKind, query: recordQuery, limit: 100, reveal_sensitive: showSensitive ? 1 : 0 }),
    ]).then(([artifactData, recordData]) => {
      setArtifacts(artifactData.items || []);
      setArtifactTotal(artifactData.total || 0);
      setRecords(recordData.items || []);
      setRecordTotal(recordData.total || 0);
    }).catch((err) => console.error('Failed to fetch QQNT evidence:', err)).finally(() => setLoading(false));
  }, [taskId, category, artifactQuery, recordKind, recordQuery, showSensitive]);

  const categoryStats = overview?.artifact_categories || [];
  const counts = overview?.record_counts || {};
  const logRange = overview?.log_time_range?.[0] || {};
  const categoryOptions = [...new Set(categoryStats.map((item) => item.artifact_category))];

  return <div className="space-y-6"><Card title="💬 QQNT 证据概览" subtitle="仅展示经格式校验后可确认的结构化内容；未解码二进制保留为文件证据。"><div className="space-y-5"><div className="grid grid-cols-2 md:grid-cols-4 gap-4"><SummaryStat label="键值记录" value={counts.kv || 0} tone="blue" /><SummaryStat label="SQLite 记录" value={counts.sqlite || 0} tone="green" /><SummaryStat label="日志时间点" value={counts.logs || 0} tone="purple" /><SummaryStat label="日志起始" value={logRange.start_time ? formatSecondsDate(logRange.start_time).slice(0, 10) : '-'} tone="gray" /></div><div className="flex flex-wrap gap-3">{categoryStats.map((item) => { const badge = openStatusBadge(item.parse_status); return <span key={`${item.artifact_category}-${item.parse_status}`} className="flex items-center gap-2 text-sm text-slate-600"><Badge variant={badge.variant}>{item.artifact_category}</Badge>{badge.label}: <b>{item.count}</b></span>; })}</div></div></Card><Card title="文件证据清单"><div className="space-y-4"><div className="flex flex-wrap gap-3"><SearchInput value={artifactQuery} onChange={setArtifactQuery} placeholder="按路径或摘要搜索..." /><select value={category} onChange={(event) => setCategory(event.target.value)} className="px-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200"><option value="">全部分类 ({artifactTotal})</option>{categoryOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></div>{loading ? <Loading /> : artifacts.length === 0 ? <Empty text="没有 QQNT 文件证据" /> : <div className="border border-slate-200 rounded-xl overflow-hidden"><Virtuoso data={artifacts} style={{ height: '38vh' }} itemContent={(index, item) => { const badge = openStatusBadge(item.parse_status); return <div className="grid grid-cols-12 gap-3 px-4 py-3 border-b border-slate-100 hover:bg-slate-50 text-xs items-center"><div className="col-span-4 font-mono text-slate-600 truncate" title={item.source_path}>{item.source_path}</div><div className="col-span-2"><Badge variant="gray" size="sm">{item.artifact_category}</Badge></div><div className="col-span-1 text-slate-600">{item.format}</div><div className="col-span-1 text-slate-600">{formatBytes(item.size)}</div><div className="col-span-2 text-slate-500 truncate" title={item.summary}>{item.summary}</div><div className="col-span-2 text-center"><Badge variant={badge.variant} size="sm">{badge.label}</Badge></div></div>; }} /></div>}</div></Card><Card title="已恢复内容"><div className="space-y-4"><div className="flex flex-wrap items-center gap-3"><div className="flex rounded-xl ring-1 ring-slate-200 overflow-hidden">{[{ id: 'kv', label: '账号与配置' }, { id: 'sqlite', label: 'SQLite 记录' }, { id: 'logs', label: '日志事件' }].map((tab) => <button key={tab.id} onClick={() => setRecordKind(tab.id)} className={`px-3 py-2 text-sm ${recordKind === tab.id ? 'bg-primary-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}>{tab.label}</button>)}</div><SearchInput value={recordQuery} onChange={setRecordQuery} placeholder="搜索已恢复内容..." /><label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={showSensitive} onChange={(event) => setShowSensitive(event.target.checked)} className="rounded border-slate-300 text-primary-600" />显示敏感原值</label></div><p className="text-xs text-slate-400">共 {recordTotal} 条。默认脱敏的标识、令牌和设备值仅在勾选后显示。</p>{loading ? <Loading /> : records.length === 0 ? <Empty text="该类别没有可验证的结构化记录" /> : <div className="border border-slate-200 rounded-xl overflow-hidden"><Virtuoso data={records} style={{ height: '38vh' }} itemContent={(index, item) => <div><div className="grid grid-cols-12 gap-3 px-4 py-3 border-b border-slate-100 hover:bg-slate-50 text-xs"><div className="col-span-3 font-mono text-slate-600 truncate" title={item.source_path}>{item.source_path}</div><div className="col-span-2 font-medium text-slate-700 truncate" title={item.label}>{item.label}</div><div className="col-span-2 text-slate-500 truncate" title={item.record_key}>{item.record_key || '-'}</div><div className="col-span-4 font-mono text-slate-600 whitespace-pre-wrap break-all max-h-24 overflow-auto">{item.value_text || '-'}</div><div className="col-span-1 text-center">{item.is_sensitive ? <Badge variant="yellow" size="sm">敏感</Badge> : <Badge variant="gray" size="sm">普通</Badge>}</div></div><AiAnalysisRow item={item} /></div>} /></div>}</div></Card></div>;
};

const WechatEvidenceTab = ({ taskId, overview }) => {
  const [artifacts, setArtifacts] = useState([]);
  const [artifactTotal, setArtifactTotal] = useState(0);
  const [records, setRecords] = useState([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [artifactQuery, setArtifactQuery] = useState('');
  const [recordQuery, setRecordQuery] = useState('');
  const [category, setCategory] = useState('');
  const [recordKind, setRecordKind] = useState('kv');
  const [showSensitive, setShowSensitive] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    Promise.all([
      getMiuiWechatArtifacts(taskId, { category, query: artifactQuery, limit: 100 }),
      getMiuiWechatRecords(taskId, { kind: recordKind, query: recordQuery, limit: 100, reveal_sensitive: showSensitive ? 1 : 0 }),
    ]).then(([artifactData, recordData]) => {
      setArtifacts(artifactData.items || []);
      setArtifactTotal(artifactData.total || 0);
      setRecords(recordData.items || []);
      setRecordTotal(recordData.total || 0);
    }).catch((err) => console.error('Failed to fetch WeChat evidence:', err)).finally(() => setLoading(false));
  }, [taskId, category, artifactQuery, recordKind, recordQuery, showSensitive]);

  const categoryStats = overview?.artifact_categories || [];
  const counts = overview?.record_counts || {};
  const logRange = overview?.log_time_range?.[0] || {};
  const categoryOptions = [...new Set(categoryStats.map((item) => item.artifact_category))];

  return <div className="space-y-6"><Card title="🟢 微信证据概览" subtitle="仅展示经格式校验后可确认的结构化内容；未解码二进制（MMKV、SQLCipher 主库）保留为文件证据。"><div className="space-y-5"><div className="grid grid-cols-2 md:grid-cols-4 gap-4"><SummaryStat label="键值记录" value={counts.kv || 0} tone="blue" /><SummaryStat label="SQLite 记录" value={counts.sqlite || 0} tone="green" /><SummaryStat label="日志时间点" value={counts.logs || 0} tone="purple" /><SummaryStat label="日志起始" value={logRange.start_time ? formatSecondsDate(logRange.start_time).slice(0, 10) : '-'} tone="gray" /></div><div className="flex flex-wrap gap-3">{categoryStats.map((item) => { const badge = openStatusBadge(item.parse_status); return <span key={`${item.artifact_category}-${item.parse_status}`} className="flex items-center gap-2 text-sm text-slate-600"><Badge variant={badge.variant}>{item.artifact_category}</Badge>{badge.label}: <b>{item.count}</b></span>; })}</div><div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="text-lg">🕸️</span><div><h4 className="font-medium text-slate-900">微信关系分析</h4><p className="text-sm text-slate-600">基于已解密消息构建的联系人/群聊关系图（需主库已解密）</p></div></div><Link to={`/wechat-graph?task_id=${encodeURIComponent(taskId)}`} className="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700">打开关系图</Link></div></div></Card><Card title="文件证据清单"><div className="space-y-4"><div className="flex flex-wrap gap-3"><SearchInput value={artifactQuery} onChange={setArtifactQuery} placeholder="按路径或摘要搜索..." /><select value={category} onChange={(event) => setCategory(event.target.value)} className="px-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200"><option value="">全部分类 ({artifactTotal})</option>{categoryOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></div>{loading ? <Loading /> : artifacts.length === 0 ? <Empty text="没有微信文件证据" /> : <div className="border border-slate-200 rounded-xl overflow-hidden"><Virtuoso data={artifacts} style={{ height: '38vh' }} itemContent={(index, item) => { const badge = openStatusBadge(item.parse_status); return <div className="grid grid-cols-12 gap-3 px-4 py-3 border-b border-slate-100 hover:bg-slate-50 text-xs items-center"><div className="col-span-4 font-mono text-slate-600 truncate" title={item.source_path}>{item.source_path}</div><div className="col-span-2"><Badge variant="gray" size="sm">{item.artifact_category}</Badge></div><div className="col-span-1 text-slate-600">{item.format}</div><div className="col-span-1 text-slate-600">{formatBytes(item.size)}</div><div className="col-span-2 text-slate-500 truncate" title={item.summary}>{item.summary}</div><div className="col-span-2 text-center"><Badge variant={badge.variant} size="sm">{badge.label}</Badge></div></div>; }} /></div>}</div></Card><Card title="已恢复内容"><div className="space-y-4"><div className="flex flex-wrap items-center gap-3"><div className="flex rounded-xl ring-1 ring-slate-200 overflow-hidden">{[{ id: 'kv', label: '账号与配置' }, { id: 'sqlite', label: 'SQLite 记录' }, { id: 'logs', label: '日志事件' }].map((tab) => <button key={tab.id} onClick={() => setRecordKind(tab.id)} className={`px-3 py-2 text-sm ${recordKind === tab.id ? 'bg-primary-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}>{tab.label}</button>)}</div><SearchInput value={recordQuery} onChange={setRecordQuery} placeholder="搜索已恢复内容..." /><label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={showSensitive} onChange={(event) => setShowSensitive(event.target.checked)} className="rounded border-slate-300 text-primary-600" />显示敏感原值</label></div><p className="text-xs text-slate-400">共 {recordTotal} 条。默认脱敏的标识、令牌和设备值仅在勾选后显示。</p>{loading ? <Loading /> : records.length === 0 ? <Empty text="该类别没有可验证的结构化记录" /> : <div className="border border-slate-200 rounded-xl overflow-hidden"><Virtuoso data={records} style={{ height: '38vh' }} itemContent={(index, item) => <div><div className="grid grid-cols-12 gap-3 px-4 py-3 border-b border-slate-100 hover:bg-slate-50 text-xs"><div className="col-span-3 font-mono text-slate-600 truncate" title={item.source_path}>{item.source_path}</div><div className="col-span-2 font-medium text-slate-700 truncate" title={item.label}>{item.label}</div><div className="col-span-2 text-slate-500 truncate" title={item.record_key}>{item.record_key || '-'}</div><div className="col-span-4 font-mono text-slate-600 whitespace-pre-wrap break-all max-h-24 overflow-auto">{item.value_text || '-'}</div><div className="col-span-1 text-center">{item.is_sensitive ? <Badge variant="yellow" size="sm">敏感</Badge> : <Badge variant="gray" size="sm">普通</Badge>}</div></div><AiAnalysisRow item={item} /></div>} /></div>}</div></Card></div>;
};

const SearchInput = ({ value, onChange, placeholder }) => <div className="relative flex-1 min-w-[220px]"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500/50" /></div>;
const Empty = ({ text }) => <p className="text-center py-8 text-slate-500">{text}</p>;
const Loading = () => <div className="flex items-center justify-center py-8"><Spinner size="md" /></div>;
const Th = ({ children }) => <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">{children}</th>;

// Expandable per-record AI analysis panel. Rendered under a recovered-content
// row when the LLM service has produced a summary for that artifact.
const AiAnalysisRow = ({ item }) => {
  const [open, setOpen] = useState(false);
  if (!item || !item.llm_summary) return null;
  const keywords = (item.llm_keywords || '').split(',').map((k) => k.trim()).filter(Boolean);
  return (
    <div className="border-t border-slate-100 bg-indigo-50/30">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 px-4 py-2 text-xs text-indigo-700 hover:bg-indigo-50/60">
        <Sparkles size={14} />
        <span className="font-medium">AI 取证分析</span>
        <span className="truncate text-slate-500">{item.llm_summary}</span>
        <ChevronDown size={14} className={`ml-auto transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-4 pb-3 text-xs text-slate-700 space-y-2">
          {item.llm_description && <p className="whitespace-pre-wrap break-words leading-relaxed">{item.llm_description}</p>}
          {keywords.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {keywords.map((kw) => <Badge key={kw} variant="blue" size="sm">{kw}</Badge>)}
            </div>
          )}
          {item.llm_model_used && <p className="text-slate-400">模型: {item.llm_model_used}</p>}
        </div>
      )}
    </div>
  );
};

// AI-analysis coverage card for the overview tab. Shows how many of the
// Android artifacts in each table have been analyzed by the LLM.
const LlmCoverageCard = ({ taskId }) => {
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    if (!taskId) return;
    getAndroidLlmSummary(taskId).then((data) => setSummary(data)).catch(() => setSummary(null));
  }, [taskId]);
  const totals = summary?.totals || {};
  const coverage = summary?.coverage || [];
  const analyzed = Number(totals.analyzed || 0);
  const total = Number(totals.total || 0);
  const pct = total > 0 ? Math.round((analyzed / total) * 100) : 0;
  if (total === 0) return null;
  return (
    <Card title="✨ AI 证据分析覆盖" subtitle="Android 工件经 LLM 自动分析后的覆盖率概览">
      <div className="space-y-4">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="flex justify-between text-xs text-slate-500 mb-1"><span>已分析 {analyzed.toLocaleString()} / {total.toLocaleString()}</span><span>{pct}%</span></div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${pct}%` }} /></div>
          </div>
        </div>
        {coverage.length > 0 && (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-4">
            {coverage.map((row) => {
              const rowPct = row.total > 0 ? Math.round((row.analyzed / row.total) * 100) : 0;
              return (
                <div key={row.table} className="rounded-lg bg-white/70 p-3">
                  <p className="text-sm font-medium text-slate-700">{row.label}</p>
                  <p className="text-xs text-slate-500">{Number(row.analyzed).toLocaleString()} / {Number(row.total).toLocaleString()}</p>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${rowPct === 100 ? 'bg-emerald-500' : rowPct > 0 ? 'bg-indigo-500' : 'bg-slate-300'}`} style={{ width: `${rowPct}%` }} /></div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
};
const SummaryStat = ({ label, value, tone }) => { const tones = { blue: 'bg-blue-50 text-blue-900', green: 'bg-emerald-50 text-emerald-900', purple: 'bg-purple-50 text-purple-900', gray: 'bg-slate-50 text-slate-900' }; const subs = { blue: 'text-primary-600', green: 'text-emerald-600', purple: 'text-purple-600', gray: 'text-slate-600' }; return <div className={`p-4 rounded-xl text-center ${tones[tone] || tones.gray}`}><p className="text-2xl font-bold break-all">{typeof value === 'number' ? value.toLocaleString() : value}</p><p className={`text-sm ${subs[tone] || subs.gray}`}>{label}</p></div>; };

export default Android;
