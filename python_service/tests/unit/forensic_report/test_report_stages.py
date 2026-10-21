"""Synthetic two-stage regression: real frozen sources/storage, scripted model."""
import base64
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.forensic_report.generation import ReportGenerationAdmissionService, ReportGenerationInputError
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.models import (
    ReportGenerationEnvelopeV5, DirectionSuggestion, parse_generation_envelope,
)
from httpserver.services.forensic_report.generation_sources import digest, material
from httpserver.services.forensic_report.generation_stages import parse_directions, validate_materialized_sources
from httpserver.services.forensic_report.generation_prompts import STAGE_DISCOVERY_SYSTEM_V1, STAGE_COMPARE_SYSTEM_V1
from httpserver.services.investigation.acquisition import canonical_json

CANARY = "CASE_SECRET_CANARY_不得出现在自主模型输入"
RAW = "台账记载收款安排，另附对照表。这里没有确认账户归属。"


def setup(tmp_path, *, paths=("/case/a.txt",), contents=None):
    root = tmp_path / "A"
    extraction = root / "extracted_files"
    extraction.mkdir(parents=True)
    db_path = root / "files.db"
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)""")
        for path in paths:
            actual = extraction / path.lstrip("/")
            actual.parent.mkdir(parents=True, exist_ok=True)
            raw = (contents or {}).get(path, RAW.encode())
            actual.write_bytes(raw)
            db.execute("INSERT INTO files(path,size,md5,llm_summary,llm_description,llm_keywords,scene_type) VALUES(?,?,?,?,?,?,?)",
                       (path, len(raw), hashlib.md5(raw).hexdigest(), CANARY, CANARY, CANARY, CANARY))
    investigation = InvestigationRepository(root / "investigation.db", "A")
    for path in paths:
        key = "file:" + path
        investigation.capture_if_absent(ResolvedEvidence(task_id="A", evidence_key=key, evidence_type="file",
                                                       normalized_path=path, source_db=str(db_path)))
        investigation.add_report_evidence(key, report_status="main", added_by="synthetic")
    task = {"id": "A", "output_files_db": str(db_path), "extraction_directory": str(extraction),
            "case_description": CANARY, "name": CANARY}
    backend = AsyncMock()
    backend.get_task.side_effect = lambda identity: task if identity == "A" else None
    reports = tmp_path / "reports"
    repository = ReportRepository(reports / "reports.db")
    writer = GenerationReportWriter(reports)
    admission = ReportGenerationAdmissionService(backend, repository)
    return task, investigation, repository, writer, admission


class Model:
    def __init__(self, *, reject_comparison=False, case_only=False):
        self.calls, self.images = [], 0
        self.reject_comparison, self.case_only = reject_comparison, case_only

    async def analyze_image(self, *, image_data, prompt):
        self.images += 1
        assert CANARY not in prompt
        return {"model": "synthetic-vision", "analysis": {"description": "机器观察到截图中存在文字。"}}

    async def chat_completion(self, system, user, **kwargs):
        self.calls.append((system, user))
        body = json.loads(user)
        if system.startswith(STAGE_DISCOVERY_SYSTEM_V1):
            source = body["materials"][0]
            item = {"title": "资金活动待核线索", "description": "应核对材料中的业务背景和账户关系。",
                    "finding_kind": "hypothesis",
                    "supporting_refs": [{"material_id": source["material_id"], "quote": source["text"][:8]}],
                    "counter_refs": [], "missing_information": ["原始业务凭据"],
                    "alternative_explanations": ["可能为正常业务安排"],
                    "baseline_direction_ids": [d["direction_id"] for d in body["baseline_directions"][:1]],
                    "case_context_quote": ""}
            if self.case_only and body["analysis_mode"] == "case_guided":
                item.update(supporting_refs=[], baseline_direction_ids=[],
                            case_context_quote=body["case_context"], title="仅案情提出的待核方向")
            response = {"directions": [item]}
        elif system.startswith(STAGE_COMPARE_SYSTEM_V1):
            source = body["materials"][0]
            response = {"baseline_direction_id": body["baseline_direction"]["direction_id"],
                        "status": "supported", "reason": "仍应保留原线索并核对。",
                        "supporting_refs": [{"material_id": source["material_id"],
                                             "quote": "不属于本材料的伪造引文" if self.reject_comparison else source["text"][:8]}],
                        "counter_refs": [], "missing_information": ["账户归属信息"], "case_context_quote": ""}
        else:
            response = {"classifications": [{
                "evidence_key": source["evidence_key"], "material_type": "document", "topics": ["funds"],
                "relations": [{"question_id": body["questions"][0]["question_id"], "relation": "supports", "reason": "核查材料记载。"}],
                "key_issue": False, "reason": "材料记载业务安排。", "basis_quote": source["basis_text"][:8],
            } for source in body["materials"]]}
        return {"model": "synthetic", "content": json.dumps(response, ensure_ascii=False)}


async def publish(admission, repository, writer, *, mode="evidence_only", base=None, context=None, llm=None):
    row = await admission.admit("A", requested_by="tester", analysis_mode=mode,
                                base_report_id=base, case_description=context)
    provider = llm or Model()
    executor = ReportGenerationExecutor(repository, writer, provider)
    await executor._execute(row.generation_id)
    done = repository.get_generation_input(row.generation_id)
    assert done.status == "completed", (done.error_code, done.error_message)
    return done, writer.read_manifest("A", done.report_id), provider


@pytest.mark.asyncio
async def test_first_stage_input_and_model_calls_ignore_case_and_old_summaries(tmp_path):
    task, investigation, repository, writer, admission = setup(tmp_path)
    before = (Path(task["output_files_db"]).read_bytes(), (tmp_path / "A/investigation.db").read_bytes())
    row = await admission.admit("A", requested_by="tester", analysis_mode="evidence_only")
    assert CANARY not in row.input_envelope_json
    frozen = parse_generation_envelope(row.input_envelope_json)
    assert frozen.case_description == "" and frozen.main_evidence[0].bound_analysis is None
    assert frozen.neutral_materials[0].text == RAW
    task["case_description"] = "另一份完全不同的案情"
    row2 = await admission.admit("A", requested_by="another-actor", analysis_mode="evidence_only")
    assert row2.input_hash == row.input_hash
    done, report, provider = await publish(admission, repository, writer)
    assert all(CANARY not in user and "另一份完全不同" not in user for _, user in provider.calls)
    assert report["stage_analysis"]["analysis_mode"] == "evidence_only"
    assert report["stage_analysis"]["directions"][0]["alternative_explanations"]
    assert report["evidence_classifications"]["items"][0]["priority"] == "P2"
    assert before == (Path(task["output_files_db"]).read_bytes(), (tmp_path / "A/investigation.db").read_bytes())


@pytest.mark.asyncio
async def test_second_stage_reuses_exact_baseline_after_live_files_and_adoption_change(tmp_path, monkeypatch):
    task, investigation, repository, writer, admission = setup(tmp_path)
    first, report_a, _ = await publish(admission, repository, writer)
    before = digest(report_a)
    (Path(task["extraction_directory"]) / "case/a.txt").write_text("改变后的文件", encoding="utf-8")
    investigation.update_report_evidence("file:/case/a.txt", report_status="excluded", updated_by="tester")
    task["case_description"] = "不应替代明确提交的案情"
    async def forbidden(*args): raise AssertionError("B must not reread live sources")
    monkeypatch.setattr("httpserver.services.forensic_report.generation_sources.freeze_materials", forbidden)
    context = "请核查是否存在异常资金流转，不能预设已经违法。"
    second, report_b, _ = await publish(admission, repository, writer, mode="case_guided",
        base=first.report_id, context=context)
    stage = report_b["stage_analysis"]
    assert stage["case_description"] == context
    assert stage["baseline_report_id"] == first.report_id
    assert stage["evidence_scope_hash"] == report_a["stage_analysis"]["evidence_scope_hash"]
    assert stage["materials"] == report_a["stage_analysis"]["materials"]
    assert len(stage["comparisons"]) == len(stage["baseline_directions"]) == 1
    assert stage["comparisons"][0]["status"] == "supported"
    assert digest(writer.read_manifest("A", first.report_id)) == before
    assert first.report_id != second.report_id


@pytest.mark.asyncio
async def test_case_only_direction_has_no_fabricated_support_and_comparison_failure_keeps_baseline(tmp_path):
    _, _, repository, writer, admission = setup(tmp_path)
    first, original, _ = await publish(admission, repository, writer)
    _, report, _ = await publish(admission, repository, writer, mode="case_guided",
        base=first.report_id, context="案情提出另一个方向，材料尚未支持。",
        llm=Model(case_only=True, reject_comparison=True))
    stage = report["stage_analysis"]
    assert stage["directions"][0]["origin"] == "case_only"
    assert stage["directions"][0]["supporting_refs"] == []
    assert stage["comparisons"][0]["status"] == "insufficient"
    assert stage["baseline_directions"] == original["stage_analysis"]["directions"]
    assert any(w.startswith("COMPARISON_REJECTED") for w in stage["warnings"])


@pytest.mark.asyncio
async def test_unreadable_source_never_falls_back_to_old_summary(tmp_path):
    task, _, repository, writer, admission = setup(tmp_path)
    (Path(task["extraction_directory"]) / "case/a.txt").unlink()
    row = await admission.admit("A", requested_by="tester", analysis_mode="evidence_only")
    assert CANARY not in row.input_envelope_json
    provider = Model()
    await ReportGenerationExecutor(repository, writer, provider)._execute(row.generation_id)
    assert repository.get_generation_input(row.generation_id).error_code == "neutral_sources_unavailable"
    assert not provider.calls


@pytest.mark.asyncio
async def test_mixed_readability_retains_all_materials_and_no_history_leaks(tmp_path):
    task, _, repository, writer, admission = setup(tmp_path, paths=("/case/a.txt", "/case/b.txt"))
    (Path(task["extraction_directory"]) / "case/b.txt").unlink()
    _, report, _ = await publish(admission, repository, writer)
    assert len(report["stage_analysis"]["materials"]) == 2
    assert len(report["evidence_classifications"]["items"]) == 2
    assert report["stage_analysis"]["materials"][1]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_image_is_read_once_without_case_and_reused_for_second_stage(tmp_path):
    task, _, repository, writer, admission = setup(tmp_path, paths=("/case/a.png",))
    # Synthetic bytes; this verifies transport isolation, not real vision quality.
    provider = Model()
    first, a, _ = await publish(admission, repository, writer, llm=provider)
    assert provider.images == 1
    assert a["stage_analysis"]["materials"][0]["kind"] == "machine_visual"
    assert a["stage_analysis"]["materials"][0]["media_base64"] == ""
    second_provider = Model()
    _, b, _ = await publish(admission, repository, writer, mode="case_guided", base=first.report_id,
        context="核查图片所示内容。", llm=second_provider)
    assert second_provider.images == 0
    assert a["stage_analysis"]["materials"] == b["stage_analysis"]["materials"]


@pytest.mark.asyncio
async def test_task_scope_and_stage_guards(tmp_path):
    _, _, repository, writer, admission = setup(tmp_path)
    with pytest.raises(ReportGenerationInputError):
        await admission.admit("A", requested_by="x", analysis_mode="evidence_only", case_description="案情")
    with pytest.raises(ReportGenerationInputError):
        await admission.admit("A", requested_by="x", analysis_mode="case_guided", base_report_id="foreign", case_description="案情")
    first, _, _ = await publish(admission, repository, writer)
    with pytest.raises(ReportGenerationInputError):
        await admission.admit("A", requested_by="x", analysis_mode="case_guided", base_report_id=first.report_id, case_description="")
    second, _, _ = await publish(admission, repository, writer, mode="case_guided", base=first.report_id, context="案情")
    with pytest.raises(ReportGenerationInputError):
        await admission.admit("A", requested_by="x", analysis_mode="case_guided", base_report_id=second.report_id, case_description="案情")


@pytest.mark.asyncio
async def test_source_hash_and_symlink_escape_are_not_read(tmp_path):
    task, _, _, _, admission = setup(tmp_path)
    source = Path(task["extraction_directory"]) / "case/a.txt"
    source.write_text("另一内容", encoding="utf-8")
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    assert parse_generation_envelope(row.input_envelope_json).neutral_materials[0].status == "unavailable"
    source.unlink()
    external = tmp_path / "outside.txt"
    external.write_text(RAW, encoding="utf-8")
    source.symlink_to(external)
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    assert parse_generation_envelope(row.input_envelope_json).neutral_materials[0].text == ""


@pytest.mark.asyncio
async def test_scope_and_neutral_content_are_hash_checked(tmp_path):
    _, _, _, _, admission = setup(tmp_path)
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    raw = json.loads(row.input_envelope_json)
    raw["neutral_materials"][0]["text"] = "tampered"
    with pytest.raises(ValueError): ReportGenerationEnvelopeV5.model_validate(raw)
    raw = json.loads(row.input_envelope_json)
    raw["main_evidence"][0]["snapshot"]["payload"]["initial_summary"] = CANARY
    with pytest.raises(ValueError): ReportGenerationEnvelopeV5.model_validate(raw)


@pytest.mark.asyncio
async def test_sqlite_sample_is_context_free_and_source_bytes_remain_unchanged(tmp_path):
    original = tmp_path / "sample.db"
    with sqlite3.connect(original) as db:
        db.execute("CREATE TABLE transactions(note TEXT)")
        db.execute("INSERT INTO transactions VALUES('合成业务记录')")
    raw = original.read_bytes()
    task, _, _, _, admission = setup(tmp_path, paths=("/case/transactions.db",),
                                     contents={"/case/transactions.db": raw})
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    source = parse_generation_envelope(row.input_envelope_json).neutral_materials[0]
    assert source.kind == "parsed_text" and "合成业务记录" in source.text
    assert "SQLITE_SCHEMA_AND_FIRST_50_ROWS_ONLY" in source.limitations
    assert CANARY not in row.input_envelope_json
    assert (Path(task["extraction_directory"]) / "case/transactions.db").read_bytes() == raw


@pytest.mark.asyncio
async def test_transcript_reuse_is_hash_bound_and_never_uses_context_notes(tmp_path):
    task, _, _, _, admission = setup(tmp_path, paths=("/case/audio.wav",))
    with sqlite3.connect(task["output_files_db"]) as db:
        db.execute("CREATE TABLE audio_transcripts(id INTEGER,task_id TEXT,file_path TEXT,md5 TEXT,status TEXT,coverage REAL,full_text TEXT,note TEXT)")
        db.execute("INSERT INTO audio_transcripts VALUES(1,?,?,?,?,?,?,?)",
            ("A", "/case/audio.wav", hashlib.md5(RAW.encode()).hexdigest(), "partial", .4, "合成转写内容", CANARY))
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    source = parse_generation_envelope(row.input_envelope_json).neutral_materials[0]
    assert source.kind == "audio_transcript" and source.text == "合成转写内容"
    assert source.status == "partial" and CANARY not in row.input_envelope_json


@pytest.mark.asyncio
async def test_corrupt_image_error_cannot_become_machine_observation(tmp_path):
    _, _, repository, writer, admission = setup(tmp_path, paths=("/case/a.png",))
    class Corrupt(Model):
        async def analyze_image(self, **kwargs):
            return {"success": False, "error_type": "image_decode_failed",
                    "analysis": {"description": "[IMAGE_CORRUPT_OR_INVALID] error text"}}
    provider = Corrupt()
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    await ReportGenerationExecutor(repository, writer, provider)._execute(row.generation_id)
    assert repository.get_generation_input(row.generation_id).error_code == "neutral_sources_unavailable"
    assert not provider.calls


@pytest.mark.asyncio
async def test_duplicate_source_quotes_do_not_count_as_independent_corroboration(tmp_path):
    _, _, _, _, admission = setup(tmp_path, paths=("/case/a.txt", "/case/copy.txt"))
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    env = parse_generation_envelope(row.input_envelope_json)
    sources = env.neutral_materials
    value = dict(title="共同线索", description="需要核查", finding_kind="hypothesis",
                 supporting_refs=[{"material_id": m.material_id, "quote": RAW[:8]} for m in sources],
                 counter_refs=[], missing_information=["形成关系"], alternative_explanations=[],
                 baseline_direction_ids=[], case_context_quote="")
    result = parse_directions(json.dumps({"directions": [value]}),
        {m.material_id: m.text for m in sources}, {m.material_id: m for m in sources}, env, set())
    assert any("不能据此计作独立佐证" in note for note in result[0].missing_information)


@pytest.mark.asyncio
async def test_newly_linked_counter_material_can_revise_the_baseline(tmp_path):
    counter = "对照记录注明该安排并未执行。"
    _, _, repository, writer, admission = setup(tmp_path, paths=("/case/a.txt", "/case/counter.txt"),
        contents={"/case/counter.txt": counter.encode()})
    first, _, _ = await publish(admission, repository, writer)

    class CounterModel(Model):
        async def chat_completion(self, system, user, **kwargs):
            body = json.loads(user)
            if system.startswith(STAGE_DISCOVERY_SYSTEM_V1):
                value = {"title": "执行情况存在差异", "description": "需要核对安排与实际执行。",
                         "finding_kind": "hypothesis",
                         "supporting_refs": [{"material_id": "m0001", "quote": RAW[:8]}],
                         "counter_refs": [{"material_id": "m0002", "quote": counter}],
                         "missing_information": ["实际执行凭据"], "alternative_explanations": ["可能仅为计划"],
                         "baseline_direction_ids": [body["baseline_directions"][0]["direction_id"]],
                         "case_context_quote": ""}
                return {"model": "synthetic", "content": json.dumps({"directions": [value]})}
            if system.startswith(STAGE_COMPARE_SYSTEM_V1):
                assert any(counter in m["text"] for m in body["materials"])
                value = {"baseline_direction_id": body["baseline_direction"]["direction_id"],
                         "status": "weakened", "reason": "对照记录削弱了实际执行的判断。",
                         "supporting_refs": [], "counter_refs": [{"material_id": "m0002", "quote": counter}],
                         "missing_information": ["执行凭据"], "case_context_quote": ""}
                return {"model": "synthetic", "content": json.dumps(value)}
            return await super().chat_completion(system, user, **kwargs)

    _, report, _ = await publish(admission, repository, writer, mode="case_guided", base=first.report_id,
                                 context="核查是否实际执行。", llm=CounterModel())
    comparison = report["stage_analysis"]["comparisons"][0]
    assert comparison["status"] == "weakened"
    assert comparison["counter_refs"][0]["material_id"] == "m0002"


@pytest.mark.parametrize("fault", ["foreign_material", "quote", "no_support", "case_leak", "baseline_id", "review_field"])
@pytest.mark.asyncio
async def test_direction_contract_rejects_unowned_or_case_contaminated_output(tmp_path, fault):
    _, _, _, _, admission = setup(tmp_path)
    row = await admission.admit("A", requested_by="x", analysis_mode="evidence_only")
    envelope = parse_generation_envelope(row.input_envelope_json)
    source = envelope.neutral_materials[0]
    value = dict(title="方向", description="待核查", finding_kind="hypothesis",
                 supporting_refs=[{"material_id": source.material_id, "quote": RAW[:8]}],
                 counter_refs=[], missing_information=["需补查"], alternative_explanations=[],
                 baseline_direction_ids=[], case_context_quote="")
    if fault == "foreign_material": value["supporting_refs"][0]["material_id"] = "other"
    if fault == "quote": value["supporting_refs"][0]["quote"] = "伪造引文"
    if fault == "no_support": value["supporting_refs"] = []
    if fault == "case_leak": value["case_context_quote"] = CANARY
    if fault == "baseline_id": value["baseline_direction_ids"] = ["foreign"]
    if fault == "review_field": value["accepted"] = True
    with pytest.raises(ValueError):
        parse_directions(json.dumps({"directions": [value]}), {source.material_id: source.text},
                         {source.material_id: source}, envelope, set())


def test_direction_and_comparison_accept_scalar_for_array_fields():
    from httpserver.services.forensic_report.models import ComparisonSuggestion, DirectionSuggestion
    value = DirectionSuggestion.model_validate({
        "title": "方向", "description": "描述", "finding_kind": "hypothesis",
        "supporting_refs": {"material_id": "m0001", "quote": "片段"},
        "counter_refs": [], "missing_information": "来源与使用人未证实",
        "alternative_explanations": "运维远程管理", "baseline_direction_ids": "d_1",
        "case_context_quote": ""})
    assert value.missing_information == ("来源与使用人未证实",)
    assert value.alternative_explanations == ("运维远程管理",)
    assert value.baseline_direction_ids == ("d_1",)
    assert len(value.supporting_refs) == 1
    assert ComparisonSuggestion.model_validate({
        "baseline_direction_id": "d_1", "status": "insufficient", "reason": "材料不足以判断",
        "supporting_refs": [], "counter_refs": None, "missing_information": "缺转写",
        "case_context_quote": ""}).counter_refs == ()
    assert "必须是数组" in STAGE_DISCOVERY_SYSTEM_V1
    assert "必须是数组" in STAGE_COMPARE_SYSTEM_V1
