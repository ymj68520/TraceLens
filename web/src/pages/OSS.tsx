import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cloud, ListTree, ScrollText, BarChart3, Play } from 'lucide-react';
import {
  getObjects,
  getAccessLogs,
  getSummary,
  getExtensionStats,
  startAnalysis,
  pollAnalysisStatus,
} from '../services/ossService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { cx, errorMessage, formatBytes } from '../lib/utils';

type OssTab = 'objects' | 'logs' | 'summary' | 'stats';

const TABS: { key: OssTab; label: string; Icon: typeof Cloud }[] = [
  { key: 'objects', label: '对象列表', Icon: ListTree },
  { key: 'logs', label: '访问日志', Icon: ScrollText },
  { key: 'summary', label: '摘要', Icon: Cloud },
  { key: 'stats', label: '统计', Icon: BarChart3 },
];

type Row = Record<string, unknown>;

function Table({ rows, keys }: { rows: Row[]; keys: string[] }) {
  if (rows.length === 0) return <EmptyState title="暂无数据" />;
  return (
    <div className="overflow-x-auto">
      <table className="table-shell">
        <thead>
          <tr>{keys.map((k) => <th key={k}>{k}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 500).map((row, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k} className="font-mono text-2xs max-w-[260px] truncate">
                  {k.toLowerCase().includes('size') ? formatBytes(Number(row[k] ?? 0)) : String(row[k] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OSS() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  const [activeTab, setActiveTab] = useState<OssTab>('objects');
  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      switch (activeTab) {
        case 'objects':
          setData(await getObjects(taskId));
          break;
        case 'logs':
          setData(await getAccessLogs(taskId));
          break;
        case 'summary':
          setData(await getSummary(taskId));
          break;
        case 'stats':
          setData(await getExtensionStats(taskId));
          break;
      }
    } catch (err) {
      setError((err as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [taskId, activeTab]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleStartAnalysis = async () => {
    if (!taskId) return;
    setAnalyzing(true);
    try {
      const res = (await startAnalysis(taskId)) as { job_id: string };
      toast.success('OSS 分析已启动');
      await pollAnalysisStatus(res.job_id, undefined, 2000);
      toast.success('OSS 分析完成');
      void load();
    } catch (err) {
      toast.error(`分析失败：${errorMessage(err)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<Cloud size={36} />} title="未选择任务" description="请选择一个包含 OSS 数据的任务。" />
      </div>
    );
  }

  const rowsOf = (d: unknown, ...keys: string[]): Row[] => {
    if (Array.isArray(d)) return d as Row[];
    const obj = (d ?? {}) as Row;
    for (const k of keys) {
      if (Array.isArray(obj[k])) return obj[k] as Row[];
    }
    return [];
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
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
        <Button
          size="sm"
          variant="primary"
          className="ml-auto"
          onClick={handleStartAnalysis}
          disabled={analyzing}
        >
          <Play size={13} />
          {analyzing ? '分析中…' : '启动 OSS 分析'}
        </Button>
      </div>

      <Card padded={false}>
        {loading ? (
          <LoadingBlock />
        ) : error ? (
          <EmptyState title="加载失败" description={error} />
        ) : activeTab === 'summary' ? (
          <div className="p-5 grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(((data as Row) ?? {}) as Row).map(([k, v]) => (
              <div key={k} className="border border-ink-100 dark:border-ink-800 rounded-md px-3 py-2">
                <p className="text-2xs text-ink-400">{k}</p>
                <p className="text-sm font-medium text-ink-900 dark:text-ink-100 mt-0.5 break-all">
                  {String(v ?? '—')}
                </p>
              </div>
            ))}
          </div>
        ) : activeTab === 'objects' ? (
          <Table rows={rowsOf(data, 'objects', 'items')} keys={['key', 'size', 'storage_class', 'last_modified']} />
        ) : activeTab === 'logs' ? (
          <Table rows={rowsOf(data, 'logs', 'items')} keys={['time', 'operation', 'bucket', 'key', 'remote_ip']} />
        ) : (
          <Table rows={rowsOf(data, 'stats', 'extensions', 'items')} keys={['extension', 'count', 'total_size']} />
        )}
      </Card>
    </div>
  );
}
