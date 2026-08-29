import { Filter, RotateCcw } from 'lucide-react';
import { useTranslation } from '../../hooks/useTranslation';
import { fromDatetimeLocal, toDatetimeLocal } from '../../pages/Timeline';

interface TimelineFilterBarProps {
  eventType: string;
  selectedDate: string;
  customStart: string;
  customEnd: string;
  isClustered: boolean;
  bucketParam: string;
  effectiveBucket: number;
  onChange: (params: Record<string, string | undefined>) => void;
}

const BUCKET_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: '60', label: '1 分钟' },
  { value: '300', label: '5 分钟' },
  { value: '900', label: '15 分钟' },
  { value: '3600', label: '1 小时' },
  { value: '21600', label: '6 小时' },
];

export default function TimelineFilterBar({
  eventType,
  selectedDate,
  customStart,
  customEnd,
  isClustered,
  bucketParam,
  effectiveBucket,
  onChange,
}: TimelineFilterBarProps) {
  const { t } = useTranslation();

  const reset = () =>
    onChange({ type: '', date: '', start: '', end: '', page: '', bucket: '', cluster: undefined });

  return (
    <div className="card card-pad">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="field-label">{t('timeline.filter.type')}</label>
          <select
            className="select w-32 text-xs"
            value={eventType}
            onChange={(e) => onChange({ type: e.target.value || undefined, page: '1' })}
          >
            <option value="">{t('timeline.filter.all')}</option>
            <option value="CREATED">{t('timeline.filter.created')}</option>
            <option value="MODIFIED">{t('timeline.filter.modified')}</option>
            <option value="DELETED">{t('timeline.filter.deleted')}</option>
          </select>
        </div>

        <div>
          <label className="field-label">按日期</label>
          <input
            type="date"
            className="input w-40 text-xs"
            value={selectedDate}
            onChange={(e) =>
              onChange({ date: e.target.value || undefined, start: '', end: '', page: '1' })
            }
          />
        </div>

        <div>
          <label className="field-label">{t('timeline.filter.custom_start')}</label>
          <input
            type="datetime-local"
            className="input w-48 text-xs"
            value={toDatetimeLocal(customStart ? Number(customStart) : null)}
            onChange={(e) =>
              onChange({
                start: fromDatetimeLocal(e.target.value)?.toString() ?? undefined,
                date: '',
                page: '1',
              })
            }
          />
        </div>
        <div>
          <label className="field-label">{t('timeline.filter.custom_end')}</label>
          <input
            type="datetime-local"
            className="input w-48 text-xs"
            value={toDatetimeLocal(customEnd ? Number(customEnd) : null)}
            onChange={(e) =>
              onChange({
                end: fromDatetimeLocal(e.target.value)?.toString() ?? undefined,
                date: '',
                page: '1',
              })
            }
          />
        </div>

        <div>
          <label className="field-label">{t('timeline.filter.bucket')}</label>
          <select
            className="select w-28 text-xs"
            value={bucketParam}
            onChange={(e) => onChange({ bucket: e.target.value, page: '1' })}
          >
            {BUCKET_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 pb-2 text-xs text-ink-600 dark:text-ink-300 cursor-pointer">
          <input
            type="checkbox"
            className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            checked={isClustered}
            onChange={(e) => onChange({ cluster: e.target.checked ? undefined : 'false', page: '1' })}
          />
          {t('timeline.filter.cluster')}
        </label>

        <div className="ml-auto flex items-center gap-2 pb-0.5">
          {bucketParam === 'auto' && (
            <span className="text-2xs text-ink-400">
              {t('timeline.filter.bucket.resolved')}: {effectiveBucket}s
            </span>
          )}
          <button
            type="button"
            onClick={reset}
            className="btn-ghost btn-sm"
            title={t('timeline.filter.reset')}
          >
            <RotateCcw size={13} />
            {t('timeline.filter.reset')}
          </button>
        </div>
      </div>

      {(eventType || selectedDate || customStart || customEnd) && (
        <p className="mt-2 text-2xs text-ink-400 flex items-center gap-1">
          <Filter size={11} />
          筛选已生效
        </p>
      )}
    </div>
  );
}
