import { Filter, RotateCcw } from 'lucide-react';
import { useTranslation } from '../../hooks/useTranslation';
import type { TranslationKey } from '../../locales/keys';
import { toDatetimeLocal } from '../../pages/Timeline';

interface TimelineFilterBarProps {
  eventType: string;
  selectedDate: string;
  customStart: string;
  customEnd: string;
  isClustered: boolean;
  bucketParam: string;
  effectiveBucket: number;
  onEventTypeChange: (value: string) => void;
  onDateChange: (value: string) => void;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
  onClusteredChange: (value: boolean) => void;
  onBucketChange: (value: string) => void;
  onReset: () => void;
}

const BUCKET_OPTIONS: { value: string; labelKey: TranslationKey }[] = [
  { value: 'auto', labelKey: 'timeline.filter.bucket.auto' },
  { value: '60', labelKey: 'timeline.filter.bucket.1m' },
  { value: '300', labelKey: 'timeline.filter.bucket.5m' },
  { value: '900', labelKey: 'timeline.filter.bucket.15m' },
  { value: '3600', labelKey: 'timeline.filter.bucket.1h' },
  { value: '21600', labelKey: 'timeline.filter.bucket.6h' },
];

export default function TimelineFilterBar({
  eventType,
  selectedDate,
  customStart,
  customEnd,
  isClustered,
  bucketParam,
  effectiveBucket,
  onEventTypeChange,
  onDateChange,
  onStartChange,
  onEndChange,
  onClusteredChange,
  onBucketChange,
  onReset,
}: TimelineFilterBarProps) {
  const { t } = useTranslation();

  return (
    <div className="card card-pad">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="field-label">{t('timeline.filter.type')}</label>
          <select
            className="select w-32 text-xs"
            value={eventType}
            onChange={(e) => onEventTypeChange(e.target.value)}
          >
            <option value="">{t('timeline.filter.all')}</option>
            <option value="CREATED">{t('timeline.filter.created')}</option>
            <option value="MODIFIED">{t('timeline.filter.modified')}</option>
            <option value="DELETED">{t('timeline.filter.deleted')}</option>
            <option value="OTHER">{t('timeline.chip.other')}</option>
          </select>
        </div>

        <div>
          <label className="field-label">{t('timeline.filter.date')}</label>
          <input
            type="date"
            className="input w-40 text-xs"
            value={selectedDate}
            onChange={(e) => onDateChange(e.target.value)}
          />
        </div>

        <div>
          <label className="field-label">{t('timeline.filter.custom_start')}</label>
          <input
            type="datetime-local"
            className="input w-48 text-xs"
            value={toDatetimeLocal(customStart ? Number(customStart) : null)}
            onChange={(e) => onStartChange(e.target.value)}
          />
        </div>
        <div>
          <label className="field-label">{t('timeline.filter.custom_end')}</label>
          <input
            type="datetime-local"
            className="input w-48 text-xs"
            value={toDatetimeLocal(customEnd ? Number(customEnd) : null)}
            onChange={(e) => onEndChange(e.target.value)}
          />
        </div>

        <div>
          <label className="field-label">{t('timeline.filter.bucket')}</label>
          <select
            className="select w-28 text-xs"
            value={bucketParam}
            onChange={(e) => onBucketChange(e.target.value)}
          >
            {BUCKET_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {t(o.labelKey)}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 pb-2 text-xs text-ink-600 dark:text-ink-300 cursor-pointer">
          <input
            type="checkbox"
            className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            checked={isClustered}
            onChange={(e) => onClusteredChange(e.target.checked)}
          />
          {t('timeline.filter.cluster')}
        </label>

        <div className="ml-auto flex items-center gap-2 pb-0.5">
          {bucketParam === 'auto' && (
            <span className="text-2xs text-ink-400">
              {t('timeline.filter.bucket.resolved')}: {effectiveBucket}s
            </span>
          )}
          <button type="button" onClick={onReset} className="btn-ghost btn-sm" title={t('timeline.filter.reset')}>
            <RotateCcw size={13} />
            {t('timeline.filter.reset')}
          </button>
        </div>
      </div>

      {(eventType || selectedDate || customStart || customEnd) && (
        <p className="mt-2 text-2xs text-ink-400 flex items-center gap-1">
          <Filter size={11} />
          {t('timeline.filter.active')}
        </p>
      )}
    </div>
  );
}
