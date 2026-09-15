import { useMemo, useState } from 'react';
import Card from '../../components/ui/Card';
import { useToast } from '../../components/ui/Toast';
import { useDebouncedValue } from '../../hooks/useUrlState';
import { ANDROID_FIELD_LABELS } from './labels';
import {
  cellText,
  exportRowsToCsv,
  filterRows,
  nextSort,
  RecordTableSection,
  sortRows,
  type RecordColumn,
  type Row,
  type SortSpec,
} from './RecordTable';
import { RecordDetailDrawer } from './RecordDetailDrawer';

const DB_COLUMNS: RecordColumn[] = [
  { key: 'db_path', label: '数据库路径', sortable: true, mono: true },
  { key: 'app', label: '所属应用', sortable: true },
  { key: 'table_count', label: '表数量', sortable: true, numeric: true },
];

interface DbTabProps {
  databases: Row[];
  loading: boolean;
  error: string | null;
  taskId: string;
  onRetry: () => void;
}

/** App-database inventory: path search, sort, row drawer, CSV export. */
export default function DbTab({ databases, loading, error, taskId, onRetry }: DbTabProps) {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [sort, setSort] = useState<SortSpec>({ key: 'db_path', dir: 'asc' });
  const [detailRow, setDetailRow] = useState<Row | null>(null);

  const filteredRows = useMemo(() => filterRows(databases, debouncedSearch), [databases, debouncedSearch]);
  const sortedRows = useMemo(() => sortRows(filteredRows, DB_COLUMNS, sort), [filteredRows, sort]);

  const handleExportCsv = () => {
    // Union export keeps parser-specific fields (wal size, encryption...) too.
    const count = exportRowsToCsv(
      sortedRows,
      `android-db-${taskId.slice(0, 8)}.csv`,
      ANDROID_FIELD_LABELS,
    );
    if (count === 0) {
      toast.info('当前筛选结果为空，没有可导出的数据库');
      return;
    }
    toast.success(`已导出 ${count} 条数据库记录到 CSV`);
  };

  return (
    <>
      <Card padded={false}>
        <RecordTableSection
          loading={loading}
          error={error}
          rows={sortedRows}
          totalCount={databases.length}
          onClearFilter={() => setSearch('')}
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="搜索数据库路径 / 所属应用…"
          columns={DB_COLUMNS}
          sort={sort}
          onSortChange={(key) => setSort((prev) => nextSort(prev, key))}
          onOpenRow={setDetailRow}
          onExport={handleExportCsv}
          onRetry={onRetry}
          emptyTitle="暂无数据库清单"
          emptyDescription="该 MIUI 备份中未发现应用数据库，请确认备份内容完整，或点击刷新重试。"
        />
      </Card>

      <RecordDetailDrawer
        row={detailRow}
        onClose={() => setDetailRow(null)}
        title={detailRow ? cellText(detailRow.db_path ?? detailRow.app) : ''}
        description={detailRow ? '应用数据库记录详情' : undefined}
        fieldLabels={ANDROID_FIELD_LABELS}
      />
    </>
  );
}
