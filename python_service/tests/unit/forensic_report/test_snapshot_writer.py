import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest

import httpserver.services.forensic_report.snapshot_writer as snapshot_writer
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
from httpserver.services.forensic_report.search_index import SnapshotSearchIndex
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter


def category_spec(category_id: str, *, page_size: int = 2) -> CategorySpec:
    return CategorySpec(
        category_id=category_id,
        platform="android",
        title=category_id,
        renderer="chat",
        source_table="sms_messages",
        page_size=page_size,
        searchable_fields=["body", "address"],
    )


def record(category_id: str, row_id: int, body: str) -> ReportRecord:
    return ReportRecord(
        record_id="rec_" + f"{row_id:064x}",
        category=category_id,
        title=f"message {row_id}",
        source_table="sms_messages",
        source_record_id=str(row_id),
        data_state=DataState.DELETED if row_id == 2 else DataState.EXISTING,
        fields={"body": body, "address": "13800138000"},
    )


class FakeAdapter:
    name = "fake"
    platform = "android"

    def probe(self, context):
        return ProbeResult(available=True)

    def categories(self, context):
        return [category_spec("android.sms")]

    def iter_records(self, context, category):
        for row_id in range(1, 4):
            yield record(category.category_id, row_id, f"验证码 {row_id}")


class PartialFailureAdapter:
    name = "partial"
    platform = "android"

    def probe(self, context):
        return ProbeResult(available=True)

    def categories(self, context):
        return [category_spec("android.broken", page_size=1), category_spec("android.good")]

    def iter_records(self, context, category):
        if category.category_id == "android.broken":
            yield record(category.category_id, 10, "orphan-secret")
            raise RuntimeError("late record failure")
        yield record(category.category_id, 11, "survivor-secret")


class DiscoveryFailureAdapter:
    name = "discovery-failure"
    platform = "android"

    def probe(self, context):
        return ProbeResult(available=True)

    def categories(self, context):
        raise RuntimeError("category discovery failure")

    def iter_records(self, context, category):
        raise AssertionError("categories should not produce records")


class BlockingAdapter:
    name = "blocking"
    platform = "android"

    def __init__(self, started, release):
        self.started = started
        self.release = release

    def probe(self, context):
        self.started.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("writer release timed out")
        return ProbeResult(available=True)

    def categories(self, context):
        return [category_spec("android.sms")]

    def iter_records(self, context, category):
        yield record(category.category_id, 20, "concurrent")


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


def write_snapshot(tmp_path, version, evidence, contexts, adapters):
    return SnapshotWriter(tmp_path, "test").write(
        version=version,
        title="Task report",
        case_description="",
        evidence=evidence,
        contexts=contexts,
        adapters=adapters,
        analysis={},
    )


def _write_in_process(report_root, version, evidence, context, started, release, result):
    try:
        final_dir = write_snapshot(
            report_root,
            version,
            [evidence],
            [context],
            [BlockingAdapter(started, release)],
        )
        result.put(("ok", str(final_dir)))
    except Exception as exc:  # pragma: no cover - only reports child failure
        result.put(("error", repr(exc)))


def test_writer_publishes_pages_only_after_manifest_is_complete(
    tmp_path: Path, report_inputs
):
    version, evidence, context = report_inputs

    final_dir = write_snapshot(tmp_path, version, [evidence], [context], [FakeAdapter()])

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
    final_dir = write_snapshot(tmp_path, version, [evidence], [context], [FakeAdapter()])

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    page_path = final_dir / manifest["categories"][0]["page_paths"][0]
    page = json.loads(page_path.read_text("utf-8"))
    digest = page.pop("sha256")
    assert digest == hashlib.sha256(
        json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    with pytest.raises(FileExistsError):
        write_snapshot(tmp_path, version, [evidence], [context], [FakeAdapter()])


def test_writer_reuses_one_shot_adapters_for_every_context(tmp_path: Path, report_inputs):
    version, evidence, context = report_inputs
    second_evidence = evidence.model_copy(update={"evidence_id": "task-2", "task_id": "task-2"})
    second_context = context.model_copy(
        update={"evidence_id": "task-2", "task_id": "task-2", "evidence_name": "phone 2"}
    )

    final_dir = write_snapshot(
        tmp_path,
        version,
        [evidence, second_evidence],
        [context, second_context],
        (adapter for adapter in [FakeAdapter()]),
    )

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    assert {category["evidence_id"] for category in manifest["categories"]} == {
        "task-1",
        "task-2",
    }


def test_writer_rolls_back_failed_category_pages_and_search(tmp_path: Path, report_inputs):
    version, evidence, context = report_inputs

    final_dir = write_snapshot(
        tmp_path, version, [evidence], [context], [PartialFailureAdapter()]
    )

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    assert [category["category_id"] for category in manifest["categories"]] == [
        "android.good"
    ]
    assert manifest["warnings"][0]["code"] == "category_failed"
    assert not list((final_dir / "data").rglob("*broken*"))
    index = SnapshotSearchIndex(final_dir / "search.sqlite3")
    assert index.search("orphan-secret", 0, 10) == (0, [])
    assert index.search("survivor-secret", 0, 10)[0] == 1


def test_writer_recovers_from_category_discovery_failure(tmp_path: Path, report_inputs):
    version, evidence, context = report_inputs

    final_dir = write_snapshot(
        tmp_path,
        version,
        [evidence],
        [context],
        [DiscoveryFailureAdapter(), FakeAdapter()],
    )

    manifest = json.loads((final_dir / "manifest.json").read_text("utf-8"))
    assert [category["category_id"] for category in manifest["categories"]] == [
        "android.sms"
    ]
    assert manifest["warnings"][0]["adapter"] == "discovery-failure"
    assert manifest["warnings"][0]["code"] == "categories_failed"


def test_second_process_cannot_touch_active_report_staging(tmp_path: Path, report_inputs):
    version, evidence, context = report_inputs
    started = multiprocessing.Event()
    release = multiprocessing.Event()
    result = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_write_in_process,
        args=(tmp_path, version, evidence, context, started, release, result),
    )
    process.start()
    assert started.wait(timeout=10)

    with pytest.raises(FileExistsError, match="generation already active"):
        write_snapshot(tmp_path, version, [evidence], [context], [FakeAdapter()])

    release.set()
    process.join(timeout=15)
    assert process.exitcode == 0
    assert result.get(timeout=2)[0] == "ok"


def test_writer_recovers_process_claim_after_worker_termination(tmp_path: Path, report_inputs):
    version, evidence, context = report_inputs
    started = multiprocessing.Event()
    release = multiprocessing.Event()
    result = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_write_in_process,
        args=(tmp_path, version, evidence, context, started, release, result),
    )
    process.start()
    assert started.wait(timeout=10)
    process.terminate()
    process.join(timeout=15)
    assert process.exitcode is not None and process.exitcode != 0

    final_dir = write_snapshot(tmp_path, version, [evidence], [context], [FakeAdapter()])
    assert (final_dir / "manifest.json").exists()


def test_windows_claim_fallback_rejects_live_and_recovers_dead_owner(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(snapshot_writer, "fcntl", None)
    claim = snapshot_writer._ReportClaim(tmp_path, "r1")
    claim.path.parent.mkdir(parents=True)
    claim.path.write_text(str(os.getpid()), "utf-8")

    with pytest.raises(FileExistsError, match="generation already active"):
        with snapshot_writer._ReportClaim(tmp_path, "r1"):
            pass

    claim.path.write_text("999999", "utf-8")
    with snapshot_writer._ReportClaim(tmp_path, "r1"):
        assert claim.path.exists()
