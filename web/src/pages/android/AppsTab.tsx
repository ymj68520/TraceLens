import { useMemo, useState } from 'react';
import Badge from '../../components/ui/Badge';
import Card from '../../components/ui/Card';
import { useToast } from '../../components/ui/Toast';
import type { StatItem } from '../../components/ui/PageScaffold';
import { useDebouncedValue } from '../../hooks/useUrlState';
import { downloadCSV } from '../../lib/exportUtils';
import { formatBytes } from '../../lib/utils';
import { ANDROID_FIELD_LABELS } from './labels';
import {
  cellText,
  filterRows,
  nextSort,
  RecordTableSection,
  sortRows,
  type RecordColumn,
  type Row,
  type SortSpec,
} from './RecordTable';
import { RecordDetailDrawer } from './RecordDetailDrawer';

type BackupType = 'system' | 'user' | 'other';

export function backupTypeOf(value: unknown): BackupType {
  if (value === 1 || value === '1') return 'system';
  if (value === 2 || value === '2') return 'user';
  return 'other';
}

const BACKUP_TYPE_LABELS: Record<BackupType, string> = {
  system: '系统应用',
  user: '用户应用',
  other: '未知类型',
};

const APP_COLUMNS: RecordColumn[] = [
  {
    key: 'app_name',
    label: '应用名',
    sortable: true,
    render: (row) => (
      <span
        className="block truncate font-medium text-ink-800 dark:text-ink-100"
        title={cellText(row.app_name ?? row.package_name)}
      >
        {cellText(row.app_name ?? row.package_name)}
      </span>
    ),
  },
  { key: 'package_name', label: '包名', sortable: true, mono: true },
  {
    key: 'backup_type',
    label: '类型',
    sortable: true,
    sortValue: (row) => backupTypeOf(row.backup_type),
    render: (row) => {
      const t = backupTypeOf(row.backup_type);
      return (
        <Badge tone={t === 'user' ? 'accent' : t === 'system' ? 'info' : 'neutral'}>
          {BACKUP_TYPE_LABELS[t]}
        </Badge>
      );
    },
  },
  {
    key: 'size_bytes',
    label: '大小',
    sortable: true,
    numeric: true,
    sortValue: (row) => Number(row.size_bytes ?? 0) || 0,
    render: (row) => formatBytes(Number(row.size_bytes ?? 0) || 0),
  },
];

interface AppsTabProps {
  apps: Row[];
  loading: boolean;
  error: string | null;
  taskId: string;
  onRetry: () => void;
}

/** Installed-application list: package search, type chips, sort, drawer, CSV. */
export default function AppsTab({ apps, loading, error, taskId, onRetry }: AppsTabProps) {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [typeFilter, setTypeFilter] = useState<BackupType | ''>('');
  const [sort, setSort] = useState<SortSpec>({ key: 'app_name', dir: 'asc' });
  const [detailRow, setDetailRow] = useState<Row | null>(null);

  // Type chips stay stable while searching — counts always reflect the
  // full, unfiltered app list.
  const typeChips = useMemo<StatItem[]>(() => {
    if (apps.length === 0) return [];
    const counts: Record<BackupType, number> = { system: 0, user: 0, other: 0 };
    apps.forEach((a) => {
      counts[backupTypeOf(a.backup_type)] += 1;
    });
    return ([['', '全部'], ['system', '系统应用'], ['user', '用户应用'], ['other', '未知类型']] as [
      BackupType | '',
      string,
    ][]).map(([key, label]) => ({
      label,
      value: key === '' ? apps.length : counts[key],
      active: typeFilter === key,
      onClick: () => setTypeFilter((prev) => (prev === key ? '' : key)),
    }));
  }, [apps, typeFilter]);

  const filteredRows = useMemo(() => {
    let result = filterRows(apps, debouncedSearch);
    if (typeFilter) result = result.filter((a) => backupTypeOf(a.backup_type) === typeFilter);
    return result;
  }, [apps, debouncedSearch, typeFilter]);

  const sortedRows = useMemo(() => sortRows(filteredRows, APP_COLUMNS, sort), [filteredRows, sort]);

  const handleExportCsv = () => {
    if (sortedRows.length === 0) {
      toast.info('当前筛选结果为空，没有可导出的应用');
      return;
    }
    downloadCSV(
      sortedRows.map((a) => ({
        app_name: cellText(a.app_name ?? a.package_name),
        package_name: cellText(a.package_name),
        backup_type: BACKUP_TYPE_LABELS[backupTypeOf(a.backup_type)],
        size_bytes: Number(a.size_bytes ?? 0) || 0,
        size_human: formatBytes(Number(a.size_bytes ?? 0) || 0),
      })),
      `android-apps-${taskId.slice(0, 8)}.csv`,
      [
        { key: 'app_name', label: '应用名' },
        { key: 'package_name', label: '包名' },
        { key: 'backup_type', label: '备份类型' },
        { key: 'size_bytes', label: '大小(字节)' },
        { key: 'size_human', label: '大小' },
      ],
    );
    toast.success(`已导出 ${sortedRows.length} 个应用到 CSV`);
  };

  const renderDetailValue = (key: string, value: unknown) => {
    if (key === 'backup_type') {
      const t = backupTypeOf(value);
      return (
        <Badge tone={t === 'user' ? 'accent' : t === 'system' ? 'info' : 'neutral'}>
          {BACKUP_TYPE_LABELS[t]}
        </Badge>
      );
    }
    return undefined;
  };

  return (
    <>
      <Card padded={false}>
        <RecordTableSection
          loading={loading}
          error={error}
          rows={sortedRows}
          totalCount={apps.length}
          onClearFilter={() => {
            setSearch('');
            setTypeFilter('');
          }}
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="搜索应用名 / 包名…"
          columns={APP_COLUMNS}
          sort={sort}
          onSortChange={(key) => setSort((prev) => nextSort(prev, key))}
          onOpenRow={setDetailRow}
          onExport={handleExportCsv}
          onRetry={onRetry}
          emptyTitle="暂无应用数据"
          emptyDescription="该 MIUI 备份中未解析到已安装应用列表，请确认备份包含应用数据，或点击刷新重试。"
          chips={typeChips}
        />
      </Card>

      <RecordDetailDrawer
        row={detailRow}
        onClose={() => setDetailRow(null)}
        title={detailRow ? cellText(detailRow.app_name ?? detailRow.package_name) : ''}
        description={detailRow ? '已安装应用记录详情' : undefined}
        fieldLabels={ANDROID_FIELD_LABELS}
        renderValue={renderDetailValue}
      />
    </>
  );
}
