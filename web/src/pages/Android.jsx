import { motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Virtuoso } from 'react-virtuoso';
import { Search, Smartphone, Database, Package, HardDrive, Calendar, FolderInput, ShieldCheck } from 'lucide-react';

import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import {
  getMiuiOverview,
  getMiuiInstalledApps,
  getMiuiDbInventory,
} from '../services/forensicsService';

// ---- helpers --------------------------------------------------------------

// MIUI backup_date is epoch milliseconds; the manifest stores it as such.
// Normalize null/0 to '-' instead of rendering the epoch.
const formatMsDate = (ms) => {
  if (!ms) return '-';
  try {
    return new Date(Number(ms)).toLocaleString();
  } catch {
    return String(ms);
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

// bak_type from the MIUI manifest: 1 = system app, 2 = user app.
const bakTypeLabel = (t) => (t === 1 ? '系统应用' : t === 2 ? '用户应用' : '未知');

// open_status values written by MiuiArtifactParsers.
const openStatusBadge = (status) => {
  if (status === 'decrypted') return { variant: 'green', label: '已解密' };
  if (status === 'parse_error') return { variant: 'red', label: '解析失败' };
  if (status === 'incomplete_limit') return { variant: 'yellow', label: '截断(超限)' };
  return { variant: 'gray', label: status || '未知' };
};

// Color + label for the decryption-status distribution bars.
const STATUS_BAR = {
  decrypted: { bg: 'bg-emerald-500', label: '已解密' },
  parse_error: { bg: 'bg-rose-500', label: '解析失败' },
  incomplete_limit: { bg: 'bg-amber-500', label: '截断(超限)' },
};

// ---- page -----------------------------------------------------------------

const Android = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');

  // Data states
  const [overview, setOverview] = useState(null);
  const [apps, setApps] = useState(null);
  const [dbInventory, setDbInventory] = useState(null);

  const currentTask = tasks.find((t) => t.id === taskId);

  useEffect(() => {
    if (!taskId) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setOverview(null);
      setApps(null);
      setDbInventory(null);

      try {
        const [ov, ap, inv] = await Promise.allSettled([
          getMiuiOverview(taskId),
          getMiuiInstalledApps(taskId),
          getMiuiDbInventory(taskId),
        ]);

        if (ov.status === 'fulfilled') setOverview(ov.value);
        if (ap.status === 'fulfilled') setApps(ap.value);
        if (inv.status === 'fulfilled') setDbInventory(inv.value);

        const hasAnyData = [ov, ap, inv].some((r) => r.status === 'fulfilled' && r.value);
        if (!hasAnyData) {
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
          <p className="mt-2 text-slate-600">解析小米 MIUI 离线备份（descript.xml + .bak），还原设备信息、已备份应用及应用数据库清单</p>
        </div>

        <Card title="选择任务">
          <p className="text-slate-500">
            请从{' '}
            <a href="/tasks" className="text-primary-600 hover:text-blue-800">任务页面</a>{' '}
            选择一个已完成 MIUI 备份分析的任务，或使用顶部任务选择器。
          </p>
        </Card>

        <Card title="MIUI 备份分析能力">
          <ul className="space-y-2 text-slate-600">
            <li>• 备份清单（设备型号 / MIUI 版本 / 备份时间 / 总大小）</li>
            <li>• 已备份应用列表（包名 / 版本 / 数据大小 / 系统或用户应用）</li>
            <li>• 应用数据库清单（表名 / 行数 / 列 / 解密状态分布）</li>
          </ul>
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
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-slate-600">加载 MIUI 备份数据...</span>
          </div>
        </Card>
      </div>
    );
  }

  const manifest = overview?.manifest || {};
  const decryptionStatus = overview?.decryption_status || [];
  const appsList = apps?.apps || [];
  const bakTypeSummary = apps?.bak_type_summary || [];
  const inventory = dbInventory?.inventory || [];
  const packageSummary = dbInventory?.package_summary || [];

  // Tab availability flags: surface (No data) when a tab's source is empty.
  const tabData = {
    overview: manifest && Object.keys(manifest).length > 0,
    apps: appsList.length > 0,
    inventory: inventory.length > 0,
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900">MIUI 备份分析</motion.h1>
        <p className="mt-2 text-slate-600">任务: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <Badge variant="blue">{currentTask.status}</Badge>
            {manifest?.device && <Badge variant="purple">{manifest.device}</Badge>}
            {manifest?.miui_version && <Badge variant="gray">{manifest.miui_version}</Badge>}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <Card title="错误">
          <div className="p-4 bg-red-50 border border-red-200 rounded-xl">
            <p className="text-red-800">{error}</p>
          </div>
        </Card>
      )}

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          {[
            { id: 'overview', label: '📦 备份概览', hasData: tabData.overview },
            { id: 'apps', label: '📱 已备份应用', hasData: tabData.apps },
            { id: 'inventory', label: '🗄️ 应用数据库清单', hasData: tabData.inventory },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`${activeTab === tab.id
                  ? 'border-blue-500 text-primary-600'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              {tab.label}
              {!tab.hasData && <span className="ml-1 text-xs text-slate-400">(无数据)</span>}
            </button>
          ))}
        </nav>
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <OverviewTab
          manifest={manifest}
          decryptionStatus={decryptionStatus}
          appsCount={appsList.length}
        />
      )}

      {/* Apps Tab */}
      {activeTab === 'apps' && (
        <AppsTab apps={appsList} bakTypeSummary={bakTypeSummary} />
      )}

      {/* Inventory Tab */}
      {activeTab === 'inventory' && (
        <InventoryTab inventory={inventory} packageSummary={packageSummary} />
      )}
    </div>
  );
};

// ---- Overview tab ---------------------------------------------------------

const OverviewTab = ({ manifest, decryptionStatus, appsCount }) => {
  if (!manifest || Object.keys(manifest).length === 0) {
    return (
      <Card title="备份概览">
        <p className="text-center py-8 text-slate-500">未找到 MIUI 备份清单 (miui_backup_manifest)</p>
      </Card>
    );
  }

  const totalDecrypted = decryptionStatus.reduce((sum, s) => sum + Number(s.count || 0), 0);

  const metaCards = [
    { icon: Smartphone, label: '设备型号', value: manifest.device || '-' },
    { icon: Package, label: 'MIUI 版本', value: manifest.miui_version || '-' },
    { icon: Calendar, label: '备份时间', value: formatMsDate(manifest.backup_date) },
    { icon: HardDrive, label: '备份总大小', value: formatBytes(manifest.total_size) },
    { icon: Package, label: '应用数 (清单)', value: manifest.package_count ?? '-' },
    { icon: FolderInput, label: '来源文件夹', value: manifest.source_folder || '-' },
  ];

  return (
    <Card title="📦 备份概览">
      <div className="space-y-6">
        {/* Manifest meta grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {metaCards.map(({ icon: Icon, label, value }) => (
            <div key={label} className="p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center gap-2 text-slate-500">
                <Icon size={16} />
                <p className="text-sm font-medium">{label}</p>
              </div>
              <p className="mt-1 text-sm text-slate-900 break-all" title={typeof value === 'string' ? value : undefined}>
                {value}
              </p>
            </div>
          ))}
        </div>

        {/* Decryption status distribution */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <ShieldCheck size={18} className="text-slate-700" />
            <h4 className="font-medium text-slate-900">应用数据库解密状态分布</h4>
            <span className="text-xs text-slate-400">(共 {totalDecrypted} 个数据库表条目)</span>
          </div>

          {totalDecrypted === 0 ? (
            <p className="text-center py-6 text-slate-500">暂无数据库清单数据</p>
          ) : (
            <div className="space-y-3">
              {/* Stacked bar */}
              <div className="flex h-6 w-full overflow-hidden rounded-lg bg-slate-100">
                {decryptionStatus.map((s) => {
                  const cfg = STATUS_BAR[s.open_status] || { bg: 'bg-slate-400', label: s.open_status };
                  const pct = totalDecrypted > 0 ? (Number(s.count) / totalDecrypted) * 100 : 0;
                  if (pct <= 0) return null;
                  return (
                    <div
                      key={s.open_status}
                      className={`${cfg.bg} transition-all`}
                      style={{ width: `${pct}%` }}
                      title={`${cfg.label}: ${s.count} (${pct.toFixed(1)}%)`}
                    />
                  );
                })}
              </div>
              {/* Legend */}
              <div className="flex flex-wrap gap-4">
                {decryptionStatus.map((s) => {
                  const cfg = STATUS_BAR[s.open_status] || { bg: 'bg-slate-400', label: s.open_status };
                  const pct = totalDecrypted > 0 ? ((Number(s.count) / totalDecrypted) * 100).toFixed(1) : '0.0';
                  return (
                    <div key={s.open_status} className="flex items-center gap-2 text-sm text-slate-600">
                      <span className={`inline-block w-3 h-3 rounded-sm ${cfg.bg}`} />
                      <span>{cfg.label}</span>
                      <span className="font-medium text-slate-900">{s.count}</span>
                      <span className="text-slate-400">({pct}%)</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
};

// ---- Apps tab -------------------------------------------------------------

const AppsTab = ({ apps, bakTypeSummary }) => {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all'); // all | 1 (system) | 2 (user)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return apps.filter((a) => {
      if (typeFilter !== 'all' && Number(a.bak_type) !== Number(typeFilter)) return false;
      if (!q) return true;
      return (
        (a.package_name || '').toLowerCase().includes(q) ||
        (a.display_name || '').toLowerCase().includes(q)
      );
    });
  }, [apps, query, typeFilter]);

  const typeCounts = useMemo(() => {
    const map = {};
    bakTypeSummary.forEach((s) => { map[s.bak_type] = s.count; });
    return map;
  }, [bakTypeSummary]);

  return (
    <Card title="📱 已备份应用">
      <div className="space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="按包名或显示名搜索..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500/50"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500/50"
          >
            <option value="all">全部应用 ({apps.length})</option>
            <option value="1">系统应用 ({typeCounts[1] || 0})</option>
            <option value="2">用户应用 ({typeCounts[2] || 0})</option>
          </select>
        </div>

        {/* Table */}
        {filtered.length === 0 ? (
          <p className="text-center py-8 text-slate-500">没有符合条件的应用</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <Th>包名</Th>
                  <Th>显示名</Th>
                  <Th>版本</Th>
                  <Th>数据大小</Th>
                  <Th>SD 大小</Th>
                  <Th>类型</Th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-slate-200">
                {filtered.slice(0, 200).map((app, idx) => (
                  <tr key={`${app.package_name}-${idx}`} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-sm text-slate-600 font-mono">{app.package_name}</td>
                    <td className="px-4 py-3 text-sm text-slate-900">{app.display_name || '-'}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-600">
                      {app.version_name || app.version_code || '-'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-600">{formatBytes(app.data_size)}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-600">{formatBytes(app.sd_size)}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={app.bak_type === 1 ? 'blue' : app.bak_type === 2 ? 'purple' : 'gray'}>
                        {bakTypeLabel(app.bak_type)}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length > 200 && (
              <p className="text-center text-xs text-slate-400 py-3">仅显示前 200 条，共 {filtered.length} 条（请使用搜索缩小范围）</p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};

const Th = ({ children }) => (
  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">{children}</th>
);

// ---- Inventory tab --------------------------------------------------------

const InventoryTab = ({ inventory, packageSummary }) => {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return inventory;
    return inventory.filter((row) => (row.package_name || '').toLowerCase().includes(q));
  }, [inventory, query]);

  return (
    <Card title="🗄️ 应用数据库清单">
      <div className="space-y-4">
        {/* Summary stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SummaryStat label="涉及应用数" value={packageSummary.length} tone="blue" />
          <SummaryStat label="数据库文件数" value={packageSummary.reduce((s, p) => s + Number(p.db_count || 0), 0)} tone="green" />
          <SummaryStat label="数据表总数" value={inventory.length} tone="purple" />
          <SummaryStat
            label="数据行总数"
            value={packageSummary.reduce((s, p) => s + Number(p.total_rows || 0), 0)}
            tone="gray"
          />
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="按包名搜索数据库..."
            className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border-0 bg-white/60 ring-1 ring-slate-200 focus:ring-2 focus:ring-primary-500/50"
          />
        </div>

        {/* Virtualized table */}
        {filtered.length === 0 ? (
          <p className="text-center py-8 text-slate-500">没有数据库清单数据</p>
        ) : (
          <div className="border border-slate-200 rounded-xl overflow-hidden">
            {/* Header */}
            <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-slate-50 text-xs font-medium text-slate-500 uppercase">
              <div className="col-span-3">包名</div>
              <div className="col-span-3">数据库路径</div>
              <div className="col-span-2">表名</div>
              <div className="col-span-1 text-right">行数</div>
              <div className="col-span-2">列</div>
              <div className="col-span-1 text-center">状态</div>
            </div>
            <Virtuoso
              data={filtered}
              style={{ height: '60vh' }}
              itemContent={(index, row) => {
                const badge = openStatusBadge(row.open_status);
                return (
                  <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs border-t border-slate-100 hover:bg-slate-50 items-center">
                    <div className="col-span-3 text-slate-600 font-mono truncate" title={row.package_name}>{row.package_name}</div>
                    <div className="col-span-3 text-slate-600 font-mono truncate" title={row.db_path}>{row.db_path}</div>
                    <div className="col-span-2 text-slate-600 font-mono truncate" title={row.table_name}>{row.table_name || '-'}</div>
                    <div className="col-span-1 text-right text-slate-600">{Number(row.row_count || 0).toLocaleString()}</div>
                    <div className="col-span-2 text-slate-500 font-mono truncate" title={row.columns}>{row.columns || '-'}</div>
                    <div className="col-span-1 text-center">
                      <Badge variant={badge.variant} size="sm">{badge.label}</Badge>
                    </div>
                  </div>
                );
              }}
            />
          </div>
        )}
      </div>
    </Card>
  );
};

const SummaryStat = ({ label, value, tone }) => {
  const tones = {
    blue: 'bg-blue-50 text-blue-900',
    green: 'bg-emerald-50 text-emerald-900',
    purple: 'bg-purple-50 text-purple-900',
    gray: 'bg-slate-50 text-slate-900',
  };
  const sub = {
    blue: 'text-primary-600',
    green: 'text-emerald-600',
    purple: 'text-purple-600',
    gray: 'text-slate-600',
  };
  return (
    <div className={`p-4 rounded-xl text-center ${tones[tone] || tones.gray}`}>
      <p className="text-2xl font-bold">{Number(value).toLocaleString()}</p>
      <p className={`text-sm ${sub[tone] || sub.gray}`}>{label}</p>
    </div>
  );
};

export default Android;
