import { useEffect, useState } from 'react';
import { Brain, Copy } from 'lucide-react';
import type { FileRecord } from '../../types/api';
import type { LlmDescription } from '../../pages/Files';
import { parseFile } from '../../services/officeService';
import { Drawer, DetailRow } from '../ui/Drawer';
import { Badge } from '../ui/Badge';
import Button from '../ui/Button';
import { LoadingBlock } from '../ui/Spinner';
import { useToast } from '../ui/Toast';
import { useTranslation } from '../../hooks/useTranslation';
import { basename, cx, errorMessage, formatBytes } from '../../lib/utils';
import {
  copyText,
  formatFileTime,
  getFilePath,
  getFileExt,
  getFileSize,
  isDeletedFile,
  isOfficePath,
} from './fileUtils';

interface FileDetailDrawerProps {
  file: FileRecord | null;
  taskId: string;
  llmResult?: LlmDescription;
  llmAvailable: boolean;
  analyzing: boolean;
  onAnalyze: (file: FileRecord) => void;
  onClose: () => void;
}

interface PreviewState {
  status: 'loading' | 'done' | 'error';
  text?: string;
  error?: string;
}

/** Office text extraction is the only content endpoint the backend offers. */
const PREVIEW_MAX_CHARS = 4000;

export default function FileDetailDrawer({
  file,
  taskId,
  llmResult,
  llmAvailable,
  analyzing,
  onAnalyze,
  onClose,
}: FileDetailDrawerProps) {
  const { t } = useTranslation();
  const toast = useToast();
  const [preview, setPreview] = useState<PreviewState | null>(null);

  const filePath = file ? getFilePath(file) : '';
  const isOffice = isOfficePath(filePath);

  // Load the Office text preview when an office document is opened. Keep the
  // last result cached per file object; a failed parse shows inline, not as a
  // toast, since the metadata view stays fully usable without it.
  useEffect(() => {
    if (!file || !taskId || !isOfficePath(getFilePath(file))) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreview({ status: 'loading' });
    parseFile(taskId, getFilePath(file))
      .then((res) => {
        if (cancelled) return;
        const r = res as { text?: string; content?: string } | null;
        setPreview({ status: 'done', text: r?.text ?? r?.content ?? '' });
      })
      .catch((err) => {
        if (cancelled) return;
        setPreview({ status: 'error', error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [file, taskId]);

  if (!file) return null;

  const rec = file as Record<string, unknown>;
  const size = getFileSize(file);
  const ext = getFileExt(filePath);
  const deleted = isDeletedFile(file);
  const md5 = typeof rec.md5 === 'string' ? rec.md5 : '';
  const sha256 = typeof rec.sha256 === 'string' ? rec.sha256 : '';

  const handleCopyPath = async () => {
    const ok = await copyText(filePath);
    if (ok) toast.success(t('files.drawer.toast_path_copied'));
    else toast.error(t('files.drawer.toast_copy_failed'));
  };

  const previewText =
    preview?.text && preview.text.length > PREVIEW_MAX_CHARS
      ? `${preview.text.slice(0, PREVIEW_MAX_CHARS)}\n${t('files.drawer.truncated').replace('{n}', String(preview.text.length))}`
      : preview?.text;

  return (
    <Drawer
      open
      onClose={onClose}
      title={basename(filePath)}
      description={filePath}
      footer={
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" onClick={() => void handleCopyPath()}>
            <Copy size={13} /> {t('files.drawer.copy_path')}
          </Button>
          <Button
            size="sm"
            disabled={!llmAvailable || analyzing}
            title={llmAvailable ? t('files.drawer.analyze_title') : t('files.drawer.analyze_offline')}
            onClick={() => onAnalyze(file)}
          >
            <Brain size={13} className={cx(analyzing && 'animate-pulse')} />
            {analyzing ? t('files.drawer.analyzing') : t('files.drawer.analyze')}
          </Button>
          {deleted && (
            <Badge tone="warning" dot className="ml-auto">
              {t('files.drawer.deleted_file')}
            </Badge>
          )}
        </div>
      }
    >
      <div>
        <p className="section-label mb-1">{t('files.drawer.section_basic')}</p>
        <DetailRow label={t('common.path')} mono>{filePath || '—'}</DetailRow>
        <DetailRow label={t('files.drawer.file_name')}>{basename(filePath) || '—'}</DetailRow>
        <DetailRow label={t('common.size')} mono>
          {formatBytes(size)}
          {size > 0 && (
            <span className="text-ink-400 dark:text-ink-500">
              {' '}· {t('files.drawer.size_bytes').replace('{n}', size.toLocaleString('en-US'))}
            </span>
          )}
        </DetailRow>
        {typeof rec.file_type === 'string' && rec.file_type && (
          <DetailRow label={t('common.type')}>{rec.file_type}</DetailRow>
        )}
        <DetailRow label={t('files.drawer.extension')} mono>{ext || t('files.drawer.none')}</DetailRow>
        {md5 && <DetailRow label="MD5" mono>{md5}</DetailRow>}
        {sha256 && <DetailRow label="SHA-256" mono>{sha256}</DetailRow>}

        <p className="section-label mb-1 mt-5">{t('files.drawer.section_timeline')}</p>
        <DetailRow label={t('files.drawer.modified_time')} mono>{formatFileTime(file.modified_time)}</DetailRow>
        <DetailRow label={t('files.drawer.created_time')} mono>{formatFileTime(file.created_time)}</DetailRow>
        <DetailRow label={t('files.drawer.accessed_time')} mono>{formatFileTime(file.accessed_time)}</DetailRow>
        <DetailRow label={t('common.status')}>
          {deleted ? (
            <Badge tone="warning">{t('files.drawer.deleted')}</Badge>
          ) : (
            <Badge tone="success">{t('files.drawer.normal')}</Badge>
          )}
        </DetailRow>

        {(llmResult || (typeof rec.llm_description === 'string' && rec.llm_description)) && (
          <>
            <p className="section-label mb-2 mt-5">{t('files.drawer.section_ai')}</p>
            <div className="rounded-md border border-ink-200 dark:border-ink-800 bg-ink-50/60 dark:bg-ink-900/60 p-3 space-y-1.5">
              {(llmResult?.summary || llmResult?.description) && (
                <p className="text-xs text-ink-800 dark:text-ink-200 leading-relaxed">
                  {llmResult?.summary || llmResult?.description}
                </p>
              )}
              {!llmResult && (
                <p className="text-xs text-ink-800 dark:text-ink-200 leading-relaxed">
                  {rec.llm_description as string}
                </p>
              )}
              {llmResult?.description && llmResult?.summary && llmResult.description !== llmResult.summary && (
                <p className="text-2xs text-ink-500 dark:text-ink-400 leading-relaxed">{llmResult.description}</p>
              )}
              {llmResult?.keywords && llmResult.keywords.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-0.5">
                  {llmResult.keywords.map((k) => (
                    <span key={k} className="chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
                      {k}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {isOffice && (
          <>
            <p className="section-label mb-2 mt-5">{t('files.drawer.section_preview')}</p>
            {!preview || preview.status === 'loading' ? (
              <LoadingBlock text={t('files.drawer.parsing')} />
            ) : preview.status === 'error' ? (
              <p className="text-2xs text-rose-600 dark:text-rose-400">
                {t('files.drawer.preview_failed').replace('{error}', preview.error ?? '')}
              </p>
            ) : previewText ? (
              <div className="code-block max-h-72 whitespace-pre-wrap text-2xs">{previewText}</div>
            ) : (
              <p className="text-2xs text-ink-400 dark:text-ink-500">{t('files.drawer.preview_empty')}</p>
            )}
          </>
        )}
      </div>
    </Drawer>
  );
}
