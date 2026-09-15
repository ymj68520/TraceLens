import type { ReactNode } from 'react';
import { Copy } from 'lucide-react';
import { Drawer, DetailRow } from '../../components/ui/Drawer';
import Button from '../../components/ui/Button';
import { useToast } from '../../components/ui/Toast';
import { formatBytes } from '../../lib/utils';
import { copyText, formatFileTime, getFileTimeMs } from '../../components/files/fileUtils';
import type { OssRow } from './ossUtils';

interface Props {
  row: OssRow | null;
  tabLabel: string;
  onClose: () => void;
}

const TIME_KEY_RE = /time|date|modified|created/i;
const SIZE_KEY_RE = /size|bytes/i;

/** Enumerated field rendering: sizes get human + raw bytes, timestamps get normalized. */
function formatDetail(key: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') {
    return <span className="text-ink-300 dark:text-ink-600">—</span>;
  }
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (SIZE_KEY_RE.test(key)) {
    const n = Number(value);
    if (Number.isFinite(n)) {
      return (
        <>
          {formatBytes(n)}
          <span className="text-ink-400 dark:text-ink-500"> · {n.toLocaleString('en-US')} 字节</span>
        </>
      );
    }
  }
  if (TIME_KEY_RE.test(key)) {
    const ms = getFileTimeMs(value);
    if (ms) return formatFileTime(value);
  }
  if (typeof value === 'number') {
    return <span className="font-mono tabular-nums">{value.toLocaleString('en-US')}</span>;
  }
  if (typeof value === 'object') {
    return <span className="font-mono text-2xs break-all">{JSON.stringify(value)}</span>;
  }
  return String(value);
}

const primaryKey = (row: OssRow): string => {
  for (const k of ['key', 'extension', 'operation', 'bucket', 'field']) {
    const v = row[k];
    if (typeof v === 'string' && v) return v;
  }
  return '';
};

/** Slide-over enumerating every field of a table row as key-value detail rows. */
export default function OssRowDrawer({ row, tabLabel, onClose }: Props) {
  const toast = useToast();
  if (!row) return null;

  const entries = Object.entries(row);
  const primary = primaryKey(row);

  const handleCopyJson = async () => {
    const ok = await copyText(JSON.stringify(row, null, 2));
    if (ok) toast.success('记录 JSON 已复制到剪贴板');
    else toast.error('复制失败，请手动复制');
  };

  return (
    <Drawer
      open
      onClose={onClose}
      title={primary || tabLabel}
      description={`${tabLabel} · ${entries.length} 个字段`}
      footer={
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" onClick={() => void handleCopyJson()}>
            <Copy size={13} /> 复制 JSON
          </Button>
          <span className="ml-auto text-2xs text-ink-400 dark:text-ink-500">{tabLabel}</span>
        </div>
      }
    >
      <div>
        <p className="section-label mb-1">全部字段</p>
        {entries.map(([key, value]) => (
          <DetailRow key={key} label={key} mono={typeof value !== 'object'}>
            {formatDetail(key, value)}
          </DetailRow>
        ))}
      </div>
    </Drawer>
  );
}
