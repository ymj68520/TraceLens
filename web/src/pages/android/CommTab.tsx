import { useMemo, useState } from 'react';
import Badge from '../../components/ui/Badge';
import Card, { CardHeader } from '../../components/ui/Card';
import { useToast } from '../../components/ui/Toast';
import { useDebouncedValue } from '../../hooks/useUrlState';
import { formatBytes } from '../../lib/utils';
import { ANDROID_FIELD_LABELS } from './labels';
import {
  cellText,
  exportRowsToCsv,
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
} from './RecordTable';
import { formatTimestampValue, RecordDetailDrawer, timestampSortValue } from './RecordDetailDrawer';

export interface CommBundle {
  overview?: unknown;
  artifacts?: unknown;
  records?: unknown;
}

interface CommTabProps {
  kind: 'qqnt' | 'wechat';
  label: string;
  bundle: CommBundle | null;
  taskId: string;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

type DetailSource = 'artifact' | 'record' | 'overview';

interface DetailTarget {
  row: Row;
  source: DetailSource;
}

type StatusTone = 'success' | 'danger' | 'warning' | 'info' | 'neutral';

/** QQ/NT 与微信共用的解析状态映射（缺失状态原样展示）。 */
function openStatusMeta(status: unknown): { tone: StatusTone; label: string } | null {
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
      return null;
  }
}

const ARTIFACT_COLUMNS: RecordColumn[] = [
  { key: 'name', label: '工件名', sortable: true },
  { key: 'path', label: '路径', mono: true },
  {
    key: 'size',
    label: '大小',
    sortable: true,
    numeric: true,
    sortValue: (row) => Number(row.size ?? 0) || 0,
    render: (row) => formatBytes(Number(row.size ?? 0) || 0),
  },
  {
    key: 'modified',
    label: '修改时间',
    sortable: true,
    sortValue: (row) => timestampSortValue(row.modified),
    render: (row) => formatTimestampValue(row.modified),
  },
];

const RECORD_COLUMNS: RecordColumn[] = [
  { key: 'title', label: '标题', sortable: true },
  {
    key: 'timestamp',
    label: '时间',
    sortable: true,
    sortValue: (row) => timestampSortValue(row.timestamp),
    render: (row) => formatTimestampValue(row.timestamp),
  },
];

function detailTitleOf(detail: DetailTarget): string {
  switch (detail.source) {
    case 'artifact':
      return cellText(detail.row.name ?? detail.row.path);
    case 'record':
      return cellText(detail.row.title ?? detail.row.name);
    default:
      return `${ANDROID_FIELD_LABELS[String(detail.row.key)] ?? String(detail.row.key)} 字段值`;
  }
}

function detailDescriptionOf(label: string, detail: DetailTarget): string {
  switch (detail.source) {
    case 'artifact':
      return `${label} 工件详情`;
    case 'record':
      return `${label} 记录详情`;
    default:
      return `${label} 概览字段`;
  }
}

/**
 * Shared tab body for QQ/NT and WeChat: overview card, plus searchable,
 * sortable artifact and record tables, each with row drawers and CSV export.
 */
export default function CommTab({ kind, label, bundle, taskId, loading, error, onRetry }: CommTabProps) {
  const toast = useToast();
  const [artifactSearch, setArtifactSearch] = useState('');
  const artifactDebounced = useDebouncedValue(artifactSearch, 250);
  const [artifactSort, setArtifactSort] = useState<SortSpec>({ key: 'modified', dir: 'desc' });
  const [recordSearch, setRecordSearch] = useState('');
  const recordDebounced = useDebouncedValue(recordSearch, 250);
  const [recordSort, setRecordSort] = useState<SortSpec>({ key: 'timestamp', dir: 'desc' });
  const [detail, setDetail] = useState<DetailTarget | null>(null);

  const overviewEntries = useMemo(
    () => extractKv(bundle?.overview).filter(([key]) => key !== 'open_status'),
    [bundle],
  );
  const statusMeta = openStatusMeta((bundle?.overview as Row | undefined)?.open_status);
  const artifacts = useMemo(() => extractRows(bundle?.artifacts), [bundle]);
  const records = useMemo(() => extractRows(bundle?.records), [bundle]);

  const filteredArtifacts = useMemo(
    () => filterRows(artifacts, artifactDebounced),
    [artifacts, artifactDebounced],
  );
  const sortedArtifacts = useMemo(
    () => sortRows(filteredArtifacts, ARTIFACT_COLUMNS, artifactSort),
    [filteredArtifacts, artifactSort],
  );
  const filteredRecords = useMemo(
    () => filterRows(records, recordDebounced),
    [records, recordDebounced],
  );
  const sortedRecords = useMemo(
    () => sortRows(filteredRecords, RECORD_COLUMNS, recordSort),
    [filteredRecords, recordSort],
  );

  const exportCsv = (rows: Row[], suffix: string, emptyHint: string) => {
    const count = exportRowsToCsv(
      rows,
      `android-${kind}-${suffix}-${taskId.slice(0, 8)}.csv`,
      ANDROID_FIELD_LABELS,
    );
    if (count === 0) {
      toast.info(emptyHint);
      return;
    }
    toast.success(`已导出 ${count} 条记录到 CSV`);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={`${label} 概览`}
          actions={
            statusMeta ? (
              <Badge tone={statusMeta.tone} dot>
                {statusMeta.label}
              </Badge>
            ) : undefined
          }
        />
        {overviewEntries.length > 0 ? (
          <KeyValueGrid
            entries={overviewEntries}
            labels={ANDROID_FIELD_LABELS}
            onSelect={(key, value) => setDetail({ row: { key, value }, source: 'overview' })}
          />
        ) : (
          <p className="text-xs text-ink-400 dark:text-ink-500">暂无概览信息。</p>
        )}
      </Card>

      <Card padded={false}>
        <RecordTableSection
          loading={loading}
          error={error}
          rows={sortedArtifacts}
          totalCount={artifacts.length}
          onClearFilter={() => setArtifactSearch('')}
          search={artifactSearch}
          onSearchChange={setArtifactSearch}
          searchPlaceholder="搜索工件名称 / 路径…"
          columns={ARTIFACT_COLUMNS}
          sort={artifactSort}
          onSortChange={(key) => setArtifactSort((prev) => nextSort(prev, key))}
          onOpenRow={(row) => setDetail({ row, source: 'artifact' })}
          onExport={() =>
            exportCsv(sortedArtifacts, 'artifacts', '当前筛选结果为空，没有可导出的工件')
          }
          onRetry={onRetry}
          emptyTitle={`暂无 ${label} 工件`}
          emptyDescription={`未在该 MIUI 备份中解析到 ${label} 相关工件，请确认备份内容完整，或点击刷新重试。`}
        />
      </Card>

      <Card padded={false}>
        <RecordTableSection
          loading={loading}
          error={error}
          rows={sortedRecords}
          totalCount={records.length}
          onClearFilter={() => setRecordSearch('')}
          search={recordSearch}
          onSearchChange={setRecordSearch}
          searchPlaceholder="搜索记录标题…"
          columns={RECORD_COLUMNS}
          sort={recordSort}
          onSortChange={(key) => setRecordSort((prev) => nextSort(prev, key))}
          onOpenRow={(row) => setDetail({ row, source: 'record' })}
          onExport={() => exportCsv(sortedRecords, 'records', '当前筛选结果为空，没有可导出的记录')}
          onRetry={onRetry}
          emptyTitle={`暂无 ${label} 记录`}
          emptyDescription={`未在该 MIUI 备份中解析到 ${label} 聊天或账号记录，请确认备份内容完整，或点击刷新重试。`}
        />
      </Card>

      <RecordDetailDrawer
        row={detail?.row ?? null}
        onClose={() => setDetail(null)}
        title={detail ? detailTitleOf(detail) : ''}
        description={detail ? detailDescriptionOf(label, detail) : undefined}
        fieldLabels={ANDROID_FIELD_LABELS}
      />
    </div>
  );
}
