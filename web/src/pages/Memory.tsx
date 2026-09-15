import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cpu, HardDrive, Info, Network, RefreshCw, Terminal as TermIcon } from 'lucide-react';
import {
  getMemoryBashHistory,
  getMemoryBootInfo,
  getMemoryNetwork,
  getMemoryProcesses,
  getMemorySummary,
} from '../services/memoryService';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';
import EmptyState from '../components/ui/EmptyState';
import { PageHeader, Segmented, StatStrip, type StatItem } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import { useDebouncedValue, useUrlState } from '../hooks/useUrlState';
import { downloadCSV } from '../lib/exportUtils';
import { errorMessage } from '../lib/utils';
import {
  cellText,
  extractKv,
  extractRows,
  filterRows,
  KeyValueGrid,
  nextSort,
  RecordTableSection,
  sortRows,
  type RecordColumn,
  type Row,
  type SortSpec,
} from './memory/RecordTable';
import {
  formatTimestampValue,
  RecordDetailDrawer,
  timestampSortValue,
} from './memory/RecordDetailDrawer';

type MemoryTab = 'summary' | 'processes' | 'network' | 'bash' | 'boot';

const MEMORY_TABS: { key: MemoryTab; label: string; Icon: typeof Cpu }[] = [
  { key: 'summary', label: '概览', Icon: Info },
  { key: 'processes', label: '进程', Icon: Cpu },
  { key: 'network', label: '网络连接', Icon: Network },
  { key: 'bash', label: 'Bash 历史', Icon: TermIcon },
  { key: 'boot', label: '启动信息', Icon: HardDrive },
];

const MEMORY_TAB_KEYS = MEMORY_TABS.map((t) => t.key);

const TAB_LABEL = Object.fromEntries(MEMORY_TABS.map((t) => [t.key, t.label])) as Record<
  MemoryTab,
  string
>;

const MEMORY_FIELD_LABELS: Record<string, string> = {
  pid: 'PID',
  ppid: '父进程 PID',
  name: '进程名',
  cmdline: '命令行',
  user: '用户',
  protocol: '协议',
  local_addr: '本地地址',
  remote_addr: '远端地址',
  state: '连接状态',
  command: '命令',
  timestamp: '时间',
  key: '字段',
  value: '值',
  offset: '偏移地址',
  session_id: '会话',
  create_time: '创建时间',
  path: '路径',
};

type BadgeTone = 'success' | 'danger' | 'warning' | 'info' | 'neutral';

function netStateTone(state: unknown): BadgeTone {
  const s = String(state ?? '').toUpperCase();
  if (s.includes('ESTABLISH')) return 'success';
  if (s.includes('LISTEN')) return 'info';
  if (s.includes('SYN') || s.includes('WAIT')) return 'warning';
  return 'neutral';
}

function NetStateBadge({ value }: { value: unknown }) {
  const s = String(value ?? '');
  if (!s) return <span className="text-ink-300 dark:text-ink-600">—</span>;
  return (
    <Badge tone={netStateTone(s)} dot>
      {s}
    </Badge>
  );
}

const PROCESS_COLUMNS: RecordColumn[] = [
  { key: 'pid', label: 'PID', sortable: true, numeric: true },
  { key: 'name', label: '进程名', sortable: true },
  { key: 'ppid', label: '父 PID', sortable: true, numeric: true },
  { key: 'user', label: '用户', sortable: true },
  { key: 'cmdline', label: '命令行', mono: true },
];

const NETWORK_COLUMNS: RecordColumn[] = [
  { key: 'protocol', label: '协议', sortable: true },
  { key: 'local_addr', label: '本地地址', sortable: true, mono: true },
  { key: 'remote_addr', label: '远端地址', sortable: true, mono: true },
  {
    key: 'state',
    label: '状态',
    sortable: true,
    render: (row) => <NetStateBadge value={row.state} />,
  },
  { key: 'pid', label: 'PID', sortable: true, numeric: true },
];

const BASH_COLUMNS: RecordColumn[] = [
  {
    key: 'timestamp',
    label: '时间',
    sortable: true,
    sortValue: (row) => timestampSortValue(row.timestamp),
    render: (row) => formatTimestampValue(row.timestamp),
  },
  { key: 'user', label: '用户', sortable: true },
  { key: 'command', label: '命令', mono: true },
];

const TAB_COLUMNS: Partial<Record<MemoryTab, RecordColumn[]>> = {
  processes: PROCESS_COLUMNS,
  network: NETWORK_COLUMNS,
  bash: BASH_COLUMNS,
};

const DEFAULT_SORTS: Record<MemoryTab, SortSpec> = {
  summary: { key: 'key', dir: 'asc' },
  processes: { key: 'pid', dir: 'asc' },
  network: { key: 'remote_addr', dir: 'asc' },
  bash: { key: 'timestamp', dir: 'desc' },
  boot: { key: 'key', dir: 'asc' },
};

interface ExportSpec {
  columns: { key: string; label: string }[];
  map?: (row: Row) => Row;
}

const EXPORT_SPECS: Partial<Record<MemoryTab, ExportSpec>> = {
  processes: {
    columns: [
      { key: 'pid', label: 'PID' },
      { key: 'name', label: '进程名' },
      { key: 'ppid', label: '父 PID' },
      { key: 'user', label: '用户' },
      { key: 'cmdline', label: '命令行' },
    ],
  },
  network: {
    columns: [
      { key: 'protocol', label: '协议' },
      { key: 'local_addr', label: '本地地址' },
      { key: 'remote_addr', label: '远端地址' },
      { key: 'state', label: '状态' },
      { key: 'pid', label: 'PID' },
    ],
  },
  bash: {
    columns: [
      { key: 'timestamp', label: '时间' },
      { key: 'user', label: '用户' },
      { key: 'command', label: '命令' },
    ],
    map: (row) => ({ ...row, timestamp: formatTimestampValue(row.timestamp) }),
  },
};

const EMPTY_COPY: Record<MemoryTab, { title: string; description: string }> = {
  summary: {
    title: '暂无概览数据',
    description: '该任务尚未生成内存取证概览信息，请确认内存镜像分析已完成，或点击刷新重新加载。',
  },
  processes: {
    title: '暂无进程数据',
    description: '该任务尚未从内存镜像中提取到进程列表，请确认内存镜像分析已完成，或点击刷新重新加载。',
  },
  network: {
    title: '暂无网络连接数据',
    description: '该任务尚未从内存镜像中提取到网络连接记录，请确认内存镜像分析已完成，或点击刷新重新加载。',
  },
  bash: {
    title: '暂无 Bash 历史记录',
    description: '该任务尚未从内存镜像中提取到 Bash 命令历史，请确认内存镜像分析已完成，或点击刷新重新加载。',
  },
  boot: {
    title: '暂无启动信息',
    description: '该任务尚未生成内存启动信息，请确认内存镜像分析已完成，或点击刷新重新加载。',
  },
};

interface TabPayload {
  data?: unknown;
  error?: string;
}

function toPayload(result: PromiseSettledResult<unknown>): TabPayload {
  return result.status === 'fulfilled' ? { data: result.value } : { error: errorMessage(result.reason) };
}

function rowTitle(tab: MemoryTab, row: Row): string {
  switch (tab) {
    case 'processes':
      return `${cellText(row.name)}（PID ${cellText(row.pid)}）`;
    case 'network':
      return `${cellText(row.local_addr)} → ${cellText(row.remote_addr)}`;
    case 'bash':
      return cellText(row.command).slice(0, 80);
    default:
      return '记录详情';
  }
}

export default function Memory() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  // Tab persisted to the URL so views survive reloads and are shareable.
  const [tabParam, setTabParam] = useUrlState('tab', 'summary');
  const activeTab: MemoryTab = (MEMORY_TAB_KEYS as string[]).includes(tabParam)
    ? (tabParam as MemoryTab)
    : 'summary';

  const [tabPayloads, setTabPayloads] = useState<Partial<Record<MemoryTab, TabPayload>>>({});
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [sort, setSort] = useState<SortSpec>(DEFAULT_SORTS.summary);
  const [detailRow, setDetailRow] = useState<Row | null>(null);

  // Load every tab once so the StatStrip chips can show a full row-count
  // overview; a single failing endpoint only degrades its own tab.
  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const [summary, processes, network, bash, boot] = await Promise.allSettled([
        getMemorySummary(taskId),
        getMemoryProcesses(taskId),
        getMemoryNetwork(taskId),
        getMemoryBashHistory(taskId),
        getMemoryBootInfo(taskId),
      ]);
      setTabPayloads({
        summary: toPayload(summary),
        processes: toPayload(processes),
        network: toPayload(network),
        bash: toPayload(bash),
        boot: toPayload(boot),
      });
      const settled: [MemoryTab, PromiseSettledResult<unknown>][] = [
        ['summary', summary],
        ['processes', processes],
        ['network', network],
        ['bash', bash],
        ['boot', boot],
      ];
      const failed = settled.filter(([, r]) => r.status === 'rejected');
      if (failed.length === MEMORY_TAB_KEYS.length) {
        const first = failed[0][1];
        toast.error(
          `内存取证数据加载失败：${first.status === 'rejected' ? errorMessage(first.reason) : '未知错误'}`,
        );
      } else if (failed.length > 0) {
        toast.error(`部分内存取证数据加载失败：${failed.map(([key]) => TAB_LABEL[key]).join('、')}`);
      }
    } finally {
      setLoading(false);
    }
    // toast identity is stable enough; keeping it out avoids reload loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleTabChange = (key: string) => {
    const next = (MEMORY_TAB_KEYS as string[]).includes(key) ? (key as MemoryTab) : 'summary';
    setTabParam(next);
    setSort(DEFAULT_SORTS[next]);
    setSearch('');
    setDetailRow(null);
  };

  const handleSortChange = (key: string) => setSort((prev) => nextSort(prev, key));

  const handleRetry = () => {
    void load();
  };

  const isKvTab = activeTab === 'summary' || activeTab === 'boot';
  const isSearchableTab = activeTab === 'processes' || activeTab === 'bash';
  const columns = useMemo(() => TAB_COLUMNS[activeTab] ?? [], [activeTab]);

  const payload = tabPayloads[activeTab];
  const error = payload?.error ?? null;
  const rawData = payload?.data;

  const rows = useMemo(() => (isKvTab ? [] : extractRows(rawData)), [isKvTab, rawData]);
  const kvEntries = useMemo(() => (isKvTab ? extractKv(rawData) : []), [isKvTab, rawData]);

  const filteredRows = useMemo(
    () => (isSearchableTab ? filterRows(rows, debouncedSearch) : rows),
    [rows, debouncedSearch, isSearchableTab],
  );
  const sortedRows = useMemo(() => sortRows(filteredRows, columns, sort), [filteredRows, columns, sort]);

  // Row-count overview chips: one per tab, clicking jumps to that tab.
  const tabCounts = useMemo(() => {
    const counts: Partial<Record<MemoryTab, number>> = {};
    MEMORY_TAB_KEYS.forEach((key) => {
      const p = tabPayloads[key];
      if (!p || p.data === null || p.data === undefined) return;
      const r = extractRows(p.data);
      counts[key] = r.length > 0 ? r.length : extractKv(p.data).length;
    });
    return counts;
  }, [tabPayloads]);

  const statChips: StatItem[] = MEMORY_TABS.map(({ key, label }) => ({
    label,
    value: tabCounts[key] ?? '—',
    active: key === activeTab,
    onClick: () => handleTabChange(key),
  }));

  const handleExportCsv = () => {
    if (!taskId) return;
    const filename = `memory-${activeTab}-${taskId.slice(0, 8)}.csv`;
    if (isKvTab) {
      if (kvEntries.length === 0) {
        toast.info('当前没有可导出的数据');
        return;
      }
      downloadCSV(
        kvEntries.map(([k, v]) => ({ key: k, value: cellText(v) })),
        filename,
        [
          { key: 'key', label: '字段' },
          { key: 'value', label: '值' },
        ],
      );
      toast.success(`已导出 ${kvEntries.length} 个字段到 CSV`);
      return;
    }
    const spec = EXPORT_SPECS[activeTab];
    if (!spec || sortedRows.length === 0) {
      toast.info('当前筛选结果为空，没有可导出的记录');
      return;
    }
    const exportRows = sortedRows.map((row) => (spec.map ? spec.map(row) : row));
    downloadCSV(exportRows, filename, spec.columns);
    toast.success(`已导出 ${exportRows.length} 条记录到 CSV`);
  };

  const renderDetailValue = (key: string, value: unknown): ReactNode => {
    if (activeTab === 'network' && key === 'state') {
      const s = String(value ?? '');
      return s ? (
        <Badge tone={netStateTone(s)} dot>
          {s}
        </Badge>
      ) : (
        <span className="text-ink-400 dark:text-ink-500">—</span>
      );
    }
    return undefined;
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<Cpu size={36} />}
          title="未选择任务"
          description="请选择一个包含内存取证数据的任务。"
        />
      </div>
    );
  }

  const detailTitle = detailRow
    ? detailRow.key !== undefined && detailRow.value !== undefined
      ? `${MEMORY_FIELD_LABELS[String(detailRow.key)] ?? String(detailRow.key)} 字段值`
      : rowTitle(activeTab, detailRow)
    : '';

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={Cpu}
        tone="rose"
        title="内存取证"
        subtitle="内存镜像中的进程、网络与命令痕迹"
        actions={
          <Button variant="secondary" size="sm" onClick={handleRetry} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> 刷新
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Segmented
          options={MEMORY_TABS.map(({ key, label, Icon }) => ({ value: key, label, icon: Icon }))}
          value={activeTab}
          onChange={handleTabChange}
        />
        <StatStrip stats={statChips} />
      </div>

      <Card padded={false}>
        <RecordTableSection
          loading={loading}
          error={error}
          rows={isKvTab ? [] : sortedRows}
          totalCount={isKvTab ? kvEntries.length : rows.length}
          onClearFilter={() => setSearch('')}
          onExport={handleExportCsv}
          onRetry={handleRetry}
          emptyTitle={EMPTY_COPY[activeTab].title}
          emptyDescription={EMPTY_COPY[activeTab].description}
          search={isSearchableTab ? search : undefined}
          onSearchChange={isSearchableTab ? setSearch : undefined}
          searchPlaceholder={
            activeTab === 'processes' ? '搜索进程名、命令行、用户…' : '搜索命令、用户、时间…'
          }
          columns={isKvTab ? undefined : columns}
          sort={sort}
          onSortChange={isKvTab ? undefined : handleSortChange}
          onOpenRow={setDetailRow}
          getRowKey={(row, i) => `${activeTab}-${i}`}
        >
          {isKvTab && (
            <KeyValueGrid
              entries={kvEntries}
              labels={MEMORY_FIELD_LABELS}
              className="p-5"
              onSelect={(key, value) => setDetailRow({ key, value })}
            />
          )}
        </RecordTableSection>
      </Card>

      <RecordDetailDrawer
        row={detailRow}
        onClose={() => setDetailRow(null)}
        title={detailTitle}
        description={detailRow ? `${TAB_LABEL[activeTab]}记录详情` : undefined}
        fieldLabels={MEMORY_FIELD_LABELS}
        renderValue={renderDetailValue}
      />
    </div>
  );
}
