import json
from pathlib import Path

import pytest

from httpserver.services.forensic_report.models import (
    AdapterContext,
    CategorySpec,
    DataState,
    EvidenceSource,
    ProbeResult,
    ReportRecord,
    ReportVersion,
    ScopeType,
)
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter


class FakeAdapter:
    name = "fake"
    platform = "android"

    def probe(self, context):
        return ProbeResult(available=True)

    def categories(self, context):
        return [
            CategorySpec(
                category_id="android.sms",
                platform="android",
                title="短信",
                renderer="chat",
                source_table="sms_messages",
                page_size=2,
                searchable_fields=["body", "address"],
            )
        ]

    def iter_records(self, context, category):
        for row_id in range(1, 4):
            yield ReportRecord(
                record_id="rec_" + f"{row_id:064x}",
                category=category.category_id,
                title=f"message {row_id}",
                source_table="sms_messages",
                source_record_id=str(row_id),
                data_state=DataState.DELETED if row_id == 2 else DataState.EXISTING,
                fields={"body": f"验证码 {row_id}", "address": "13800138000"},
            )


@pytest.fixture
def report_inputs():
    version = ReportVersion(
        report_id="r1",
        version=1,
        scope_type=ScopeType.TASK,
        scope_id="task-1",
        status="generating",
        title="Task report",
        task_ids=["task-1"],
    )
    evidence = EvidenceSource(evidence_id="task-1", task_id="task-1", name="phone")
    context = AdapterContext(
        scope_type=ScopeType.TASK,
        scope_id="task-1",
        evidence_id="task-1",
        task_id="task-1",
        evidence_name="phone",
        db_paths={},
        source_fingerprints={},
    )
    return version, evidence, context


def test_writer_publishes_pages_only_after_manifest_is_complete(
    tmp_path: Path, report_inputs
):
    version, evidence, context = report_inputs

    final_dir = SnapshotWriter(tmp_path, "test").write(
        version=version,
        title="Task report",
        case_description="",
        evidence=[evidence],
        contexts=[context],
        adapters=[FakeAdapter()],
        analysis={},
    )

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    category = manifest["categories"][0]
    assert category["total"] == 3
    assert category["deleted"] == 1
    assert category["pages"] == 2
    assert not (tmp_path / ".staging" / "r1").exists()
    assert all((final_dir / path).exists() for path in category["page_paths"])


def test_writer_uses_nonrecursive_page_hash_and_refuses_existing_report(
    tmp_path: Path, report_inputs
):
    version, evidence, context = report_inputs
    writer = SnapshotWriter(tmp_path, "test")
    final_dir = writer.write(
        version=version,
        title="Task report",
        case_description="",
        evidence=[evidence],
        contexts=[context],
        adapters=[FakeAdapter()],
        analysis={},
    )

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    page_path = final_dir / manifest["categories"][0]["page_paths"][0]
    page = json.loads(page_path.read_text("utf-8"))
    digest = page.pop("sha256")
    assert digest == __import__("hashlib").sha256(
        json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    with pytest.raises(FileExistsError):
        writer.write(
            version=version,
            title="Task report",
            case_description="",
            evidence=[evidence],
            contexts=[context],
            adapters=[FakeAdapter()],
            analysis={},
        )
