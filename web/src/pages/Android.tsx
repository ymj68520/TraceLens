import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Smartphone, Package, Database, MessageSquare, Sparkles } from 'lucide-react';
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
import Card, { CardHeader } from '../components/ui/Card';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import Badge from '../components/ui/Badge';
import { cx, formatBytes } from '../lib/utils';

type AndroidTab = 'overview' | 'apps' | 'db' | 'qqnt' | 'wechat' | 'llm';

const TABS: { key: AndroidTab; label: string; Icon: typeof Smartphone }[] = [
  { key: 'overview', label: '备份概览', Icon: Smartphone },
  { key: 'apps', label: '已安装应用', Icon: Package },
  { key: 'db', label: '数据库清单', Icon: Database },
  { key: 'qqnt', label: 'QQ/NT', Icon: MessageSquare },
  { key: 'wechat', label: '微信', Icon: MessageSquare },
  { key: 'llm', label: 'AI 摘要', Icon: Sparkles },
];

const fmtMs = (ms?: number | string | null) => {
  if (!ms) return '—';
  const d = new Date(Number(ms));
  return Number.isNaN(d.getTime()) ? String(ms) : d.toLocaleString();
};

const openStatusTone = (status?: string): { tone: 'success' | 'danger' | 'warning' | 'info' | 'neutral'; label: string } => {
  switch (status) {
    case 'decrypted':
      return { tone: 'success', label: '已解密' };
    case 'parsed':
      return { tone: 'success', label: '已解析' };
    case 'parse_error':
      return { tone: 'danger', label: '解析失败' };
    case 'incomplete_limit':
    case 'limit_exceeded':
      return { tone: 'warning', label: '截断(超限)' };
    case 'recognized':
      return { tone: 'info', label: '已识别' };
    case 'encrypted_locked':
      return { tone: 'warning', label: '已发现未解密' };
    case 'not_found':
      return { tone: 'neutral', label: '未发现主库' };
    default:
      return { tone: 'neutral', label: status || '未知' };
  }
};

type Row = Record<string, unknown>;

function SimpleTable({ rows, columns }: { rows: Row[]; columns: { key: string; label: string; render?: (r: Row) => React.ReactNode }[] }) {
  if (rows.length === 0) return <EmptyState title="暂无数据" />;
  return (
    <div className="overflow-x-auto">
      <table className="table-shell">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key}>{c.render ? c.render(row) : String(row[c.key] ?? '—')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Android() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');

  const [activeTab, setActiveTab] = useState<AndroidTab>('overview');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Record<AndroidTab, unknown>>({
    overview: null,
    apps: null,
    db: null,
    qqnt: null,
    wechat: null,
    llm: null,
  });

  const load = useCallback(
    async (tab: AndroidTab) => {
      if (!taskId) return;
      setLoading(true);
      setError(null);
      try {
        switch (tab) {
          case 'overview': {
            const ov = await getMiuiOverview(taskId);
            setData((d) => ({ ...d, overview: ov }));
            break;
          }
          case 'apps': {
            const apps = await getMiuiInstalledApps(taskId);
            setData((d) => ({ ...d, apps }));
            break;
          }
          case 'db': {
            const db = await getMiuiDbInventory(taskId);
            setData((d) => ({ ...d, db }));
            break;
          }
          case 'qqnt': {
            const [ov, artifacts, records] = await Promise.all([
              getMiuiQqntOverview(taskId),
              getMiuiQqntArtifacts(taskId),
              getMiuiQqntRecords(taskId),
            ]);
            setData((d) => ({ ...d, qqnt: { overview: ov, artifacts, records } }));
            break;
          }
          case 'wechat': {
            const [ov, artifacts, records] = await Promise.all([
              getMiuiWechatOverview(taskId),
              getMiuiWechatArtifacts(taskId),
              getMiuiWechatRecords(taskId),
            ]);
            setData((d) => ({ ...d, wechat: { overview: ov, artifacts, records } }));
            break;
          }
          case 'llm': {
            const llm = await getAndroidLlmSummary(taskId);
            setData((d) => ({ ...d, llm }));
            break;
          }
        }
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [taskId],
  );

  useEffect(() => {
    if (taskId) void load(activeTab);
  }, [taskId, activeTab, load]);

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<Smartphone size={36} />} title="未选择任务" description="请选择一个 MIUI 备份分析任务。" />
      </div>
    );
  }

  const tabContent = () => {
    if (loading) return <LoadingBlock />;
    if (error) return <EmptyState title="加载失败" description={error} />;

    if (activeTab === 'overview') {
      const ov = (data.overview ?? {}) as Row;
      return (
        <Card>
          <CardHeader title="MIUI 备份概览" />
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(ov).map(([k, v]) => (
              <div key={k} className="border border-ink-100 dark:border-ink-800 rounded-md px-3 py-2">
                <p className="text-2xs text-ink-400">{k}</p>
                <p className="text-sm font-medium text-ink-900 dark:text-ink-100 mt-0.5 break-all">
                  {String(v ?? '—')}
                </p>
              </div>
            ))}
          </div>
        </Card>
      );
    }

    if (activeTab === 'apps') {
      const rows = ((data.apps as { apps?: Row[] })?.apps ?? []) as Row[];
      return (
        <Card padded={false}>
          <SimpleTable
            rows={rows}
            columns={[
              { key: 'app_name', label: '应用', render: (r) => String(r.app_name ?? r.package_name ?? '—') },
              { key: 'package_name', label: '包名', render: (r) => <span className="font-mono text-xs">{String(r.package_name ?? '—')}</span> },
              { key: 'backup_type', label: '类型', render: (r) => (r.backup_type === 1 ? '系统应用' : r.backup_type === 2 ? '用户应用' : '未知') },
              { key: 'size_bytes', label: '大小', render: (r) => formatBytes(Number(r.size_bytes ?? 0)) },
            ]}
          />
        </Card>
      );
    }

    if (activeTab === 'db') {
      const rows = ((data.db as { databases?: Row[] })?.databases ?? []) as Row[];
      return (
        <Card padded={false}>
          <SimpleTable
            rows={rows}
            columns={[
              { key: 'db_path', label: '数据库路径', render: (r) => <span className="font-mono text-xs break-all">{String(r.db_path ?? '—')}</span> },
              { key: 'app', label: '所属应用' },
              { key: 'table_count', label: '表数量' },
            ]}
          />
        </Card>
      );
    }

    if (activeTab === 'qqnt' || activeTab === 'wechat') {
      const bundle = (activeTab === 'qqnt' ? data.qqnt : data.wechat) as {
        overview?: Row;
        artifacts?: { artifacts?: Row[] };
        records?: { records?: Row[] };
      } | null;
      const ov = bundle?.overview ?? {};
      const st = openStatusTone(ov.open_status as string);
      const artifacts = bundle?.artifacts?.artifacts ?? [];
      const records = bundle?.records?.records ?? [];
      return (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title={activeTab === 'qqnt' ? 'QQ/NT 概览' : '微信概览'}
              actions={<Badge tone={st.tone}>{st.label}</Badge>}
            />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(ov)
                .filter(([k]) => k !== 'open_status')
                .map(([k, v]) => (
                  <div key={k} className="border border-ink-100 dark:border-ink-800 rounded-md px-3 py-2">
                    <p className="text-2xs text-ink-400">{k}</p>
                    <p className="text-sm font-medium text-ink-900 dark:text-ink-100 mt-0.5 break-all">{String(v ?? '—')}</p>
                  </div>
                ))}
            </div>
          </Card>

          <Card padded={false}>
            <div className="px-5 py-3 border-b border-ink-200 dark:border-ink-800">
              <h4 className="card-title">工件（{artifacts.length}）</h4>
            </div>
            <SimpleTable
              rows={artifacts.slice(0, 200)}
              columns={[
                { key: 'name', label: '名称', render: (r) => String(r.name ?? r.path ?? '—') },
                { key: 'size', label: '大小', render: (r) => formatBytes(Number(r.size ?? 0)) },
                { key: 'modified', label: '修改时间', render: (r) => fmtMs(r.modified as number) },
              ]}
            />
          </Card>

          <Card padded={false}>
            <div className="px-5 py-3 border-b border-ink-200 dark:border-ink-800">
              <h4 className="card-title">记录（{records.length}）</h4>
            </div>
            <SimpleTable
              rows={records.slice(0, 200)}
              columns={[
                { key: 'title', label: '标题', render: (r) => String(r.title ?? r.name ?? '—') },
                { key: 'timestamp', label: '时间', render: (r) => fmtMs(r.timestamp as number) },
              ]}
            />
          </Card>
        </div>
      );
    }

    // llm tab
    const llm = data.llm as { summary?: string } | null;
    return (
      <Card>
        <CardHeader title="AI 分析摘要" />
        {llm?.summary ? (
          <p className="text-sm text-ink-700 dark:text-ink-300 leading-relaxed whitespace-pre-wrap">{llm.summary}</p>
        ) : (
          <EmptyState title="暂无 AI 摘要" />
        )}
      </Card>
    );
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden w-fit flex-wrap">
        {TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={cx(
              'px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-colors',
              activeTab === key
                ? 'bg-accent-600 text-white'
                : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
            )}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>
      {tabContent()}
    </div>
  );
}
