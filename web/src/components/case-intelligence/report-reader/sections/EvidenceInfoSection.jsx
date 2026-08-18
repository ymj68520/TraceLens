/**
 * EvidenceInfoSection — renders the 证据信息 chapter.
 * Same metadata-driven pattern as CaseInfoSection.
 */
import { SectionCard, Field } from './shared';
import { val } from './reportSectionUtils';
import { EVIDENCE_INFO_FIELDS } from './metadataFields';

export default function EvidenceInfoSection({ metadata, onEdit }) {
  return (
    <SectionCard title="证据信息" onEdit={onEdit}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3">
        {EVIDENCE_INFO_FIELDS.map((f) => (
          <Field key={f.key} label={f.label}>
            {val(metadata?.[f.key])}
          </Field>
        ))}
      </dl>
    </SectionCard>
  );
}
