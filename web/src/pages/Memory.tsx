import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, Network, Terminal as TermIcon, HardDrive, Info } from 'lucide-react';
import {
  getMemorySummary,
  getMemoryProcesses,
  getMemoryNetwork,
  getMemoryBashHistory,
  getMemoryBootInfo,
} from '../services/memoryService';
import Card from '../components/ui/Card';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { cx } from '../lib/utils';

type MemoryTab = 'summary' | 'processes' | 'network' | 'bash' | 'boot';

const TABS: { key: MemoryTab; label: string; Icon: typeof Cpu }[] = [
  { key: 'summary', label: '概览', Icon: Info },
  { key: 'processes', label: '进程', Icon: Cpu },
  { key: 'network', label: '网络连接', Icon: Network },
  { key: 'bash', label: 'Bash 历史', Icon: TermIcon },
  { key: 'boot', label: '启动信息', Icon: HardDrive },
];

type Row = Record<string, unknown>;

function Rows({ data, keys }: { data: unknown; keys: string[] }) {
  const rows = (Array.isArray(data) ? data : ((data as Row)?.processes ?? (data as Row)?.connections ?? (data as Row)?.entries ?? (data as Row)?.items ?? [])) as Row[];
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
                <td key={k} className="font-mono text-2xs max-w-[240px] truncate">
                  {String(row[k] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Memory() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');

  const [activeTab, setActiveTab] = useState<MemoryTab>('summary');
  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      switch (activeTab) {
        case 'summary':
          setData(await getMemorySummary(taskId));
          break;
        case 'processes':
          setData(await getMemoryProcesses(taskId, search));
          break;
        case 'network':
          setData(await getMemoryNetwork(taskId));
          break;
        case 'bash':
          setData(await getMemoryBashHistory(taskId, search));
          break;
        case 'boot':
          setData(await getMemoryBootInfo(taskId));
          break;
      }
    } catch (err) {
      setError((err as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [taskId, activeTab, search]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 250);
    return () => clearTimeout(t);
  }, [load]);

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<Cpu size={36} />} title="未选择任务" description="请选择一个包含内存取证数据的任务。" />
      </div>
    );
  }

  const keyColumns: Record<MemoryTab, string[]> = {
    summary: ['key', 'value'],
    processes: ['pid', 'name', 'ppid', 'cmdline', 'user'],
    network: ['protocol', 'local_addr', 'remote_addr', 'state', 'pid'],
    bash: ['command', 'timestamp'],
    boot: ['key', 'value'],
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
        {(activeTab === 'processes' || activeTab === 'bash') && (
          <input
            type="text"
            className="input w-64 py-1.5 text-xs"
            placeholder={activeTab === 'processes' ? '搜索进程名…' : '搜索命令关键字…'}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}
      </div>

      <Card padded={false}>
        {loading ? (
          <LoadingBlock />
        ) : error ? (
          <EmptyState title="加载失败" description={error} />
        ) : activeTab === 'summary' || activeTab === 'boot' ? (
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
        ) : (
          <Rows data={data} keys={keyColumns[activeTab]} />
        )}
      </Card>
    </div>
  );
}
