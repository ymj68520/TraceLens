/**
 * CaseInfoSection — renders the 案件信息 chapter.
 * Reads values from the task metadata dict; renders every field (empty values
 * show "—") to match the reference report schema.
 * `autoFields` names the fields whose value was derived from the analysis
 * rather than typed by the analyst; those get an "自动" badge.
 */
import { SectionCard, Field, val } from './shared';
import { CASE_INFO_FIELDS } from './metadataFields';

export default function CaseInfoSection({ metadata, onEdit, autoFields }) {
  const auto = new Set(autoFields || []);
  return (
    <SectionCard title="案件信息" onEdit={onEdit}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">
        {CASE_INFO_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} badge={auto.has(f.key) ? '自动' : null}>
            {val(metadata?.[f.key])}
          </Field>
        ))}
      </dl>
    </SectionCard>
  );
}
