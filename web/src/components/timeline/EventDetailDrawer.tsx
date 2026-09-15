import { Braces, Copy } from 'lucide-react';
import { Drawer, DetailRow } from '../ui/Drawer';
import { useToast } from '../ui/Toast';
import { useTranslation } from '../../hooks/useTranslation';
import type { TranslationKey } from '../../locales/keys';
import {
  basename,
  formatBytes,
  formatDateTime,
  formatRelativeTime,
} from '../../lib/utils';
import {
  EVENT_TYPE_LABEL,
  EVENT_TYPE_TEXT,
  normalizeEventType,
  toUnixMs,
  type ClusterDetailEvent,
} from './eventTypes';

/* ---------------------------------------------------------------------------
 * Right-hand detail panel for a single timeline event. Shows the structured
 * fields first, then any extra scalar fields the backend attached, plus a raw
 * JSON preview. Footer copies the path / the full event as JSON.
 * ------------------------------------------------------------------------- */

/** Fields rendered by dedicated DetailRows below. */
const KNOWN_KEYS = new Set(['timestamp', 'event_type', 'file_path', 'file_size']);

/** Translated labels for common extra fields; unknown keys render verbatim. */
const EXTRA_LABEL_KEYS: Partial<Record<string, TranslationKey>> = {
  file_name: 'timeline.cluster.label.file_name',
  extension: 'timeline.cluster.label.extension',
  ext: 'timeline.cluster.label.extension',
  deleted: 'timeline.cluster.label.deleted',
  process: 'timeline.cluster.label.process',
  cmdline: 'timeline.cluster.label.cmdline',
  source: 'timeline.cluster.label.source',
  description: 'common.description',
  crtime: 'timeline.cluster.label.created_time',
  mtime: 'timeline.cluster.label.modified_time',
  atime: 'timeline.cluster.label.accessed_time',
};

/** Technical extra-field labels shown verbatim (no translation needed). */
const EXTRA_LABEL_VERBATIM: Record<string, string> = {
  md5: 'MD5',
  sha1: 'SHA-1',
  sha256: 'SHA-256',
  pid: 'PID',
  uid: 'UID',
  gid: 'GID',
};

const writeClipboard = async (text: string): Promise<boolean> => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the legacy path (non-secure contexts).
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
};

interface EventDetailDrawerProps {
  event: ClusterDetailEvent | null;
  onClose: () => void;
}

export default function EventDetailDrawer({ event, onClose }: EventDetailDrawerProps) {
  const { t } = useTranslation();
  const toast = useToast();

  if (!event) return null;

  const path = event.file_path ? String(event.file_path) : '';
  const ms = toUnixMs(event.timestamp);
  const eventType = normalizeEventType(event.event_type);
  const rawType = event.event_type ? String(event.event_type) : '—';
  const size = event.file_size;
  const json = JSON.stringify(event, null, 2);

  const extras = Object.entries(event).filter(
    ([k, v]) =>
      !KNOWN_KEYS.has(k) &&
      v !== null &&
      v !== undefined &&
      v !== '' &&
      typeof v !== 'object',
  );

  /** Resolved display label + mono flag for an extra field (unknown → verbatim). */
  const extraLabelOf = (k: string): { label: string; mono: boolean } => {
    const key = EXTRA_LABEL_KEYS[k];
    if (key) return { label: t(key), mono: false };
    const verbatim = EXTRA_LABEL_VERBATIM[k];
    if (verbatim) return { label: verbatim, mono: false };
    return { label: k, mono: true };
  };

  const copyWithToast = async (text: string, message: string) => {
    const ok = await writeClipboard(text);
    if (ok) toast.success(message);
    else toast.error(t('timeline.cluster.toast_copy_failed'));
  };

  return (
    <Drawer
      open
      onClose={onClose}
      width="lg"
      title={basename(path) || t('timeline.cluster.detail_title')}
      description={path || undefined}
      footer={
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={!path}
            onClick={() => void copyWithToast(path, t('timeline.cluster.toast_path_copied'))}
          >
            <Copy size={13} />
            {t('timeline.cluster.copy_path')}
          </button>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => void copyWithToast(json, t('timeline.cluster.toast_json_copied'))}
          >
            <Braces size={13} />
            {t('timeline.cluster.copy_json')}
          </button>
        </div>
      }
    >
      <div className="mb-3">
        <p className="section-label mb-1.5">{t('timeline.cluster.section_basic')}</p>
        <DetailRow label={t('timeline.cluster.field_timestamp')}>{ms ? formatDateTime(ms) : '—'}</DetailRow>
        <DetailRow label={t('timeline.cluster.field_relative')}>{ms ? formatRelativeTime(ms) : '—'}</DetailRow>
        <DetailRow label={t('timeline.cluster.field_event_type')}>
          <span className={`font-medium ${EVENT_TYPE_TEXT[eventType]}`}>
            {eventType === 'OTHER' && rawType !== '—' ? rawType : t(EVENT_TYPE_LABEL[eventType])}
          </span>
        </DetailRow>
        <DetailRow label={t('timeline.cluster.field_path')} mono>
          {path || '—'}
        </DetailRow>
        <DetailRow label={t('timeline.cluster.field_size')}>
          {size === undefined || size === null || size === '' ? '—' : formatBytes(Number(size))}
        </DetailRow>
      </div>

      {extras.length > 0 && (
        <div className="mb-3">
          <p className="section-label mb-1.5">{t('timeline.cluster.section_fields')}</p>
          {extras.map(([k, v]) => {
            const { label, mono } = extraLabelOf(k);
            return (
              <DetailRow key={k} label={label} mono={mono}>
                {String(v)}
              </DetailRow>
            );
          })}
        </div>
      )}

      <div>
        <p className="section-label mb-1.5">{t('timeline.cluster.section_raw')}</p>
        <pre className="code-block max-h-56 overflow-auto text-2xs">{json}</pre>
      </div>
    </Drawer>
  );
}
