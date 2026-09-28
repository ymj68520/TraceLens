"""Two independent R2 versions can both use c001 without cross-report lookup."""

import hashlib
import json
from datetime import datetime, timezone

from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.models import (
    CitationManifestEntry, GenerationReportManifest, ScopeType, StructuredReportSection,
)
from httpserver.services.forensic_report.narrative_reader import read_narrative_version_strict
from httpserver.services.forensic_report.repository import ReportRepository


def test_c001_lookup_is_scoped_by_task_and_report(tmp_path):
    report_root = tmp_path / "reports"
    report_root.mkdir()
    repo = ReportRepository(report_root / "reports.db")
    writer = GenerationReportWriter(report_root)
    expected = {}
    for task_id, result_marker in (("synthetic-A", "a"), ("synthetic-B", "b")):
        key = f"android_artifact:v1:{task_id}:{result_marker * 64}:sms:1"
        frozen = json.dumps({"schema_version": 3, "task_id": task_id, "evidence_key": key}, sort_keys=True)
        row = repo.create_generation_input(task_id, requested_by="synthetic-reviewer",
                                           input_schema_version=3, prompt_version="final-report:v3",
                                           input_envelope_json=frozen,
                                           input_hash=hashlib.sha256(frozen.encode()).hexdigest())
        assert repo.claim_generation(row.generation_id) is not None
        report_id = f"report-{task_id}"
        manifest = GenerationReportManifest(
            report_id=report_id, scope_type=ScopeType.TASK, scope_id=task_id, task_id=task_id,
            generation_id=row.generation_id, title="合成范围测试", prompt_version="final-report:v3",
            input_hash=row.input_hash, model="test-only-mock",
            generated_at=datetime.now(timezone.utc).isoformat(),
            sections=(StructuredReportSection(heading="短信", content="独立报告。", citation_ids=("c001",)),),
            citations=(CitationManifestEntry(citation_id="c001", evidence_key=key,
                                             evidence_captured_at=1),),
        )
        final_dir = writer.publish(task_id=task_id, report_id=report_id, manifest=manifest)
        repo.complete_generation_publication(row.generation_id, report_id=report_id,
                                             title=manifest.title,
                                             manifest_path=str((final_dir / "manifest.json").relative_to(report_root)),
                                             model="test-only-mock")
        expected[(task_id, report_id, "c001")] = key
    for (task_id, report_id, citation_id), key in expected.items():
        version, manifest = read_narrative_version_strict(report_root / "reports.db", report_root,
                                                          task_id, report_id)
        assert version.status == "ready"
        assert next(item for item in manifest.citations if item.citation_id == citation_id).evidence_key == key
    assert read_narrative_version_strict(report_root / "reports.db", report_root,
                                         "synthetic-A", "report-synthetic-B") is None
    assert read_narrative_version_strict(report_root / "reports.db", report_root,
                                         "synthetic-B", "report-synthetic-A") is None
