/**
 * CaseInfoSection — renders the 案件信息 chapter.
 * Reads values from the task metadata dict; renders every field (empty values
 * show "—") to match the reference report schema.
 */
import { SectionCard, Field, val } from './shared';
import { CASE_INFO_FIELDS } from './metadataFields';

export default function CaseInfoSection({ metadata, onEdit }) {
  return (
    <SectionCard title="案件信息" onEdit={onEdit}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">
        {CASE_INFO_FIELDS.map((f) => (
          <Field key={f.key} label={f.label}>
            {val(metadata?.[f.key])}
          </Field>
        ))}
      </dl>
    </SectionCard>
  );
}
