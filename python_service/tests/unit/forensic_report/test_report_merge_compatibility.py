"""The two independently developed v3 contracts retain their schema identity."""
import json
import pytest
from test_report_concurrency import input9, execute, TimedModel
from httpserver.services.forensic_report.models import (
    GenerationReportManifest, ReportGenerationEnvelopeV5, parse_generation_envelope,
)
from httpserver.services.forensic_report.generation_prompts import REPORT_GENERATION_ENVELOPE_COMPAT


def test_upstream_schema5_v3_and_local_schema9_v4_are_both_readable():
    modern = input9(count=6)
    legacy = {k: v for k, v in modern.model_dump(mode='json').items()
              if k in ReportGenerationEnvelopeV5.model_fields}
    legacy.update(schema_version=5, prompt_version='final-report:evidence-only:v3')
    restored = parse_generation_envelope(json.dumps(legacy, ensure_ascii=False))
    assert restored.schema_version == 5
    assert restored.prompt_version in REPORT_GENERATION_ENVELOPE_COMPAT[5]
    assert parse_generation_envelope(modern.model_dump_json()) == modern


@pytest.mark.asyncio
async def test_v3_manifest_does_not_require_v9_planning_and_v9_stays_strict(tmp_path):
    report, _, _ = await execute(tmp_path, input9(count=6), TimedModel(delay=0))
    old = report.model_dump(mode='json')
    old.update(schema_version='1.2', prompt_version='final-report:evidence-only:v3')
    old.pop('organization')
    old.pop('appendices')
    assert GenerationReportManifest.model_validate(old).schema_version == '1.2'
    invalid = report.model_dump(mode='json')
    invalid['prompt_version'] = 'final-report:evidence-only:v1'
    with pytest.raises(ValueError):
        GenerationReportManifest.model_validate(invalid)
