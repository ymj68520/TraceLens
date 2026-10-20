"""Synthetic protocol tests; not a real-model classification accuracy claim."""
import hashlib
import json

import pytest

from httpserver.services.forensic_report.generation_classification import (
    BASIS_LIMIT, classification_input, classification_questions, classified_groups,
    parse_classifications, unassessed_classification,
)
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.models import (
    EnvelopeEvidenceItemV3, EnvelopeSnapshotV3, ReportClassifications,
    ReportGenerationEnvelopeV4, parse_generation_envelope,
)
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.narrative_reader import read_narrative_version_strict
from httpserver.services.investigation.models import FileSnapshotPayload, AndroidArtifactSnapshotPayload
from httpserver.services.investigation.acquisition import canonical_json

TEXT = "聊天中约定付款安排，金额记载存在不一致，需要核对。"
BACKGROUND = "核查付款安排是否与聊天记录一致。核查账号归属。"


def item(path="/documents/ledger.xlsx", text=TEXT, deleted=0):
    key = "file:" + path
    return EnvelopeEvidenceItemV3(evidence_key=key, report_status="main",
        snapshot=EnvelopeSnapshotV3(task_id="A", evidence_key=key, evidence_type="file",
            captured_at=1, payload=FileSnapshotPayload(
                normalized_path=path, initial_summary=text, is_deleted=deleted)))


def envelope(items):
    return ReportGenerationEnvelopeV4(
        prompt_version="final-report:v4", task_id="A", case_description=BACKGROUND,
        main_evidence=tuple(sorted(items, key=lambda i: i.evidence_key)),
        allowed_report_evidence_ids=tuple(sorted(i.evidence_key for i in items)),
    )


def suggestion(key, relation="supports", key_issue=False):
    return dict(evidence_key=key, material_type="transaction_record",
                topics=["funds", "communications"],
                relations=[dict(question_id="q001", relation=relation, reason="需核查付款安排。")],
                key_issue=key_issue, reason="摘要涉及付款和聊天。",
                basis_quote="聊天中约定付款安排")


def classify(value, **kwargs):
    inputs = [classification_input(value)]
    return parse_classifications(json.dumps({"classifications": [suggestion(value.evidence_key, **kwargs)]}),
                                 inputs, classification_questions(BACKGROUND), "synthetic")[0]


@pytest.mark.parametrize("relation,key_issue,priority", [
    ("supports", True, "P1"), ("inconsistent", False, "P1"),
    ("supports", False, "P2"), ("background", True, "P3"), ("unknown", True, "unassessed"),
])
def test_priority_is_independent_from_deletion_and_review(relation, key_issue, priority):
    result = classify(item(deleted=1), relation=relation, key_issue=key_issue)
    assert result.priority == priority
    assert result.topics == ("funds", "communications")
    assert result.material_states == ("deleted", "incomplete_provenance")
    assert "recovered" not in result.material_states
    assert result.review_status == "pending"
    assert result.basis_type == "initial_analysis"


def test_chapter_ownership_uses_topics_not_path_or_deleted_state():
    values = [item("/home/A/ledger.xlsx"), item("/Users/A/Downloads/ledger.xlsx", deleted=1)]
    result = ReportClassifications(questions=classification_questions(BACKGROUND),
                                  items=tuple(classify(v) for v in values))
    groups = classified_groups(envelope(values), result)
    assert [(key, len(items)) for key, name, items in groups] == [("funds", 2)]
    assert all(len(c.topics) == 2 for c in result.items)


@pytest.mark.parametrize("fault", ["quote", "foreign_key", "unknown_question", "missing", "duplicate", "review", "priority", "bool"])
def test_untrusted_classification_must_match_frozen_scope(fault):
    value = item()
    entry = suggestion(value.evidence_key)
    entries = [entry]
    if fault == "quote": entry["basis_quote"] = "真实资金已到账"
    if fault == "foreign_key": entry["evidence_key"] = "file:/other"
    if fault == "unknown_question": entry["relations"][0]["question_id"] = "other"
    if fault == "missing": entries = []
    if fault == "duplicate": entries.append(dict(entry))
    if fault == "review": entry["review_status"] = "confirmed"
    if fault == "priority": entry["priority"] = "P1"
    if fault == "bool": entry["key_issue"] = "false"
    with pytest.raises(ValueError):
        parse_classifications(json.dumps({"classifications": entries}),
                              [classification_input(value)], classification_questions(BACKGROUND), "m")


def test_basis_cannot_be_borrowed_from_another_material():
    a, b = item("/a", "甲材料记载"), item("/b", TEXT)
    with pytest.raises(ValueError):
        parse_classifications(json.dumps({"classifications": [
            suggestion(a.evidence_key), suggestion(b.evidence_key)]}),
            [classification_input(a), classification_input(b)], classification_questions(BACKGROUND), "m")


def test_insufficient_content_is_unknown_not_low_and_cannot_invent_source():
    value = item(text="")
    result = unassessed_classification(classification_input(value))
    assert result.priority == "unassessed" and not result.topics
    assert "insufficient_content" in result.material_states and result.basis_quote == ""
    assert classified_groups(envelope([value]), ReportClassifications(items=(result,)))[0][0] == "unclassified"


def test_reading_scope_is_explicit_and_quotes_outside_sent_scope_are_rejected():
    value = item(text="甲" * BASIS_LIMIT + TEXT)
    source = classification_input(value)
    assert source["basis_truncated"] and len(source["basis_text"]) == BASIS_LIMIT
    with pytest.raises(ValueError):
        parse_classifications(json.dumps({"classifications": [suggestion(value.evidence_key)]}),
                              [source], classification_questions(BACKGROUND), "m")


def test_background_questions_are_bounded_without_dropping_punctuation_heavy_input():
    background = "甲；乙。" * 1000
    questions = classification_questions(background)
    # Repeated identical windows may share one question, without changing content.
    assert len(questions) <= 32
    assert all(q.text in background and len(q.text) <= 500 for q in questions)
    assert classification_questions("") == ()


def test_android_record_remains_a_record_and_not_original_database_text():
    key = "android_artifact:synthetic"
    payload = AndroidArtifactSnapshotPayload(task_id="A", result_set_id="a" * 64,
        artifact_kind="sms", record_id=1, snapshot_sha256="b" * 64,
        source_revision="c" * 64, record_hash="d" * 64, record_fields={"body": TEXT},
        normalized_fields={}, parser_name="synthetic", provenance={}, coverage={})
    value = EnvelopeEvidenceItemV3(evidence_key=key, report_status="main",
        snapshot=EnvelopeSnapshotV3(task_id="A", evidence_key=key, evidence_type="android_artifact",
                                    captured_at=1, payload=payload))
    result = classify(value)
    assert result.material_type == "android_artifact" and result.basis_type == "android_record"
    assert result.review_status == "pending" and "incomplete_provenance" in result.material_states


@pytest.mark.asyncio
async def test_failed_batch_is_retried_once_with_the_validation_error(tmp_path):
    class LLM:
        calls = 0
        async def chat_completion(self, system, user, **kwargs):
            self.calls += 1
            body = json.loads(user)
            if "correction" not in body:
                return {"content": "not JSON", "finish_reason": "stop"}
            assert body["correction"].startswith("上一次输出未通过协议校验")
            return {"model": "m", "finish_reason": "stop", "content": json.dumps({"classifications": [
                suggestion(v["evidence_key"]) for v in body["materials"]]})}
    llm = LLM()
    executor = ReportGenerationExecutor(repository=ReportRepository(tmp_path / "reports.db"),
        writer=GenerationReportWriter(tmp_path / "reports"), llm_service=llm)
    values = [item(f"/file-{i}") for i in range(7)] + [item("/empty", text="")]
    result = await executor._classify_evidence(envelope(values))
    assert llm.calls == 4 and len(result.items) == 8
    assert sum(c.assessment_status == "failed" for c in result.items) == 0
    assert sum(c.assessment_status == "classified" for c in result.items) == 7
    assert sum(c.assessment_status == "insufficient" for c in result.items) == 1


@pytest.mark.asyncio
async def test_batch_rejected_twice_keeps_its_items_failed_and_visible(tmp_path):
    class LLM:
        calls = 0
        async def chat_completion(self, system, user, **kwargs):
            self.calls += 1
            return {"content": "not JSON", "finish_reason": "stop"}
    llm = LLM()
    executor = ReportGenerationExecutor(repository=ReportRepository(tmp_path / "reports.db"),
        writer=GenerationReportWriter(tmp_path / "reports"), llm_service=llm)
    values = [item(f"/file-{i}") for i in range(7)] + [item("/empty", text="")]
    result = await executor._classify_evidence(envelope(values))
    assert llm.calls == 4 and len(result.items) == 8
    assert sum(c.assessment_status == "failed" for c in result.items) == 7
    assert all(c.priority == "unassessed" for c in result.items)


def test_quote_survives_whitespace_artifacts_but_not_foreign_text():
    value = item()
    wrapped = dict(suggestion(value.evidence_key), basis_quote="聊天中约定\n付款安排")
    result = parse_classifications(json.dumps({"classifications": [wrapped]}),
                                   [classification_input(value)],
                                   classification_questions(BACKGROUND), "m")[0]
    assert result.basis_quote == "聊天中约定\n付款安排"
    with pytest.raises(ValueError):
        parse_classifications(json.dumps({"classifications": [
            dict(suggestion(value.evidence_key), basis_quote="真实资金\t已到账")]}),
            [classification_input(value)], classification_questions(BACKGROUND), "m")


def test_prompt_pins_enum_spelling_and_android_guard():
    from httpserver.services.forensic_report.generation_prompts import CLASSIFICATION_SYSTEM_V1
    assert '"funds"(资金活动)' in CLASSIFICATION_SYSTEM_V1
    assert "值只能输出英文枚举本身" in CLASSIFICATION_SYSTEM_V1
    assert "普通文件永远不得输出该值" in CLASSIFICATION_SYSTEM_V1


@pytest.mark.asyncio
async def test_batches_keep_every_item_even_when_provider_stays_unavailable(tmp_path):
    class LLM:
        calls = 0
        async def chat_completion(self, system, user, **kwargs):
            self.calls += 1
            raise RuntimeError("network down")  # non-HTTPError must not be swallowed
    executor = ReportGenerationExecutor(repository=ReportRepository(tmp_path / "reports.db"),
        writer=GenerationReportWriter(tmp_path / "reports"), llm_service=LLM())
    with pytest.raises(RuntimeError):
        await executor._classify_evidence(envelope([item("/a")]))


@pytest.mark.asyncio
async def test_existing_executor_publishes_classification_and_reader_keeps_exact_version(tmp_path):
    first, second = item("/ledger.xlsx", deleted=1), item("/empty.txt", text="")
    frozen = envelope([first, second])
    before = canonical_json(frozen)
    root = tmp_path / "reports"
    repository = ReportRepository(root / "reports.db")
    admitted = repository.create_generation_input("A", requested_by="tester", input_schema_version=4,
        prompt_version=frozen.prompt_version, input_envelope_json=before,
        input_hash=hashlib.sha256(before.encode()).hexdigest())

    class LLM:
        async def chat_completion(self, system, user, **kwargs):
            if kwargs:
                body = {"classifications": [suggestion(first.evidence_key, "inconsistent")]}
            elif "group_ids" in user:
                body = {"title": "合成报告", "sections": [
                    {"heading": "案件背景", "brief": "待核事项", "group_ids": []},
                    {"heading": "资金", "brief": "材料", "group_ids": ["funds"]},
                    {"heading": "待分类", "brief": "范围", "group_ids": ["unclassified"]}]}
            else:
                body = {"heading": "材料", "content": "仍需核查。",
                        "citations": [{"citation_id": "c1", "evidence_key":
                            second.evidence_key if second.evidence_key in user else first.evidence_key}]}
            return {"model": "synthetic", "content": json.dumps(body)}

    executor = ReportGenerationExecutor(repository=repository, writer=GenerationReportWriter(root), llm_service=LLM())
    await executor._execute(admitted.generation_id)
    done = repository.get_generation_input(admitted.generation_id)
    assert done.status == "completed", done.error_message
    version, manifest = read_narrative_version_strict(root / "reports.db", root, "A", done.report_id)
    assert manifest.schema_version == "1.1"
    lookup = {c.evidence_key: c for c in manifest.evidence_classifications.items}
    assert lookup[first.evidence_key].priority == "P1"
    assert lookup[second.evidence_key].priority == "unassessed"
    assert canonical_json(frozen) == before
    assert canonical_json(parse_generation_envelope(before)) == before
    assert read_narrative_version_strict(root / "reports.db", root, "B", done.report_id) is None
    assert repository.get_generation_input(admitted.generation_id).input_envelope_json == before
