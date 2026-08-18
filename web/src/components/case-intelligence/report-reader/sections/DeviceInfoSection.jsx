/**
 * DeviceInfoSection — renders the 设备基本信息 chapter (39 items).
 * The backend synthesizes one record whose keys are the Chinese item labels;
 * this component lists them all, showing "—" for missing values.
 */
import { SectionCard, Field, EmptySection } from './shared';
import { val } from './reportSectionUtils';

export default function DeviceInfoSection({ pageData }) {
  const record = pageData?.records?.[0] || {};
  const entries = Object.entries(record).filter(([k]) => k !== '_category');

  return (
    <SectionCard title="设备基本信息" total={entries.length || undefined}>
      {entries.length === 0 ? (
        <EmptySection text="未检测到设备基本信息（解析器未输出该检材的设备属性）。" />
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
