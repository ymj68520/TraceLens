/**
 * DeviceInfoSection — renders 设备基本信息 for one platform.
 *
 * The backend synthesizes ONE record whose keys are the Chinese item labels
 * (39 for Android, the registry-derived set for Windows, host metrics for
 * Linux); this component lists them all, showing "—" for missing values.
 *
 * `pageData.category` identifies the platform, whose label the backend already
 * puts in the node title (设备基本信息（Windows）…). The chip repeats it in the
 * card header so the three platforms stay tellable apart at a glance.
 */
import { SectionCard, Field, val, EmptySection } from './shared';

const PLATFORM_BY_CATEGORY = {
  device_info: { label: 'Android', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' },
  win_device_info: { label: 'Windows', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' },
  linux_device_info: { label: 'Linux', className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300' },
};

function PlatformChip({ category }) {
  const platform = PLATFORM_BY_CATEGORY[category];
  if (!platform) return null;
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] font-semibold rounded ${platform.className}`}>
      {platform.label}
    </span>
  );
}

export default function DeviceInfoSection({ pageData, title = '设备基本信息' }) {
  const record = pageData?.records?.[0] || {};
  const entries = Object.entries(record).filter(([k]) => k !== '_category');

  return (
    <SectionCard
      title={title}
      total={entries.length || undefined}
      action={<PlatformChip category={pageData?.category} />}
    >
      {entries.length === 0 ? (
        <EmptySection text="未检测到设备基本信息（该任务的产物未包含可识别的设备属性，或平台尚未判定）。" />
      ) : (
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">
          {entries.map(([label, value]) => (
            <Field key={label} label={label}>
              {val(value)}
            </Field>
          ))}
        </dl>
      )}
    </SectionCard>
  );
}
