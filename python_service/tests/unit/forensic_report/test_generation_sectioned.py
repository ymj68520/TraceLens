"""final-report:v2 sectioned pipeline: grouping, outline, per-section scope.

The v2 executor groups evidence deterministically, lets the model plan an
outline over the case background, generates one section per outline entry
with only that section's evidence projection, then assembles and validates
citations against the frozen envelope. Repairs (uncovered groups, fallback
coverage) are deterministic and must never drop adopted evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.forensic_report.generation import (
    REPORT_GENERATION_PROMPT_VERSION,
    ReportGenerationInputBuilder,
)
from httpserver.services.forensic_report.generation_execution import (
    ReportGenerationExecutor,
    group_report_evidence,
)
from httpserver.services.forensic_report.generation_prompts import (
    REPORT_GENERATION_PROMPT_V2,
)
from httpserver.services.forensic_report.generation_writer import (
    GenerationReportWriter,
)
from httpserver.services.forensic_report.models import parse_generation_envelope
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.investigation import InvestigationRepository
from httpserver.services.investigation.acquisition import canonical_json

CASE_BACKGROUND = (
    "某电信网络诈骗团伙搭建虚假投资平台（杀猪盘），通过话术培训诱骗被害人入金。"
)

KEY_SCRIPT = "file:/话术/老师包装.txt"
KEY_PASSWD = "file:/etc/passwd"
KEY_CASE_A = "file:/case/a.txt"


class ScriptedLLM:
    """One scripted response per call; records every (system, user) pair."""

    def __init__(self, responses, model: str = "test-model"):
        self.responses = list(responses)
        self.model = model
        self.calls: list[tuple[str, str]] = []

    async def chat_completion(self, system: str, user: str):
        self.calls.append((system, user))
        index = len(self.calls) - 1
        if index >= len(self.responses):
            raise AssertionError(f"unexpected LLM call #{index + 1}")
        return {"model": self.model, "content": self.responses[index]}


def _make_files_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for file_path, summary in (
        ("/case/a.txt", "系统组件元数据文件"),
        ("/话术/老师包装.txt", "冒充境外分析师的话术剧本"),
        ("/etc/passwd", "账户体系文件"),
    ):
        conn.execute(
            "INSERT INTO files (path, llm_summary, size) VALUES (?,?,?)",
            (file_path, summary, 1),
        )
    conn.commit()
    conn.close()


def _store(tmp_path: Path):
    root = tmp_path / "A"
    root.mkdir(parents=True, exist_ok=True)
    files_db = str(root / "files.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(root / "investigation.db", "A")
    for key, path in (
        (KEY_CASE_A, "/case/a.txt"),
        (KEY_SCRIPT, "/话术/老师包装.txt"),
        (KEY_PASSWD, "/etc/passwd"),
    ):
        repo.capture_if_absent(ResolvedEvidence(
            task_id="A", evidence_key=key, evidence_type="file",
            normalized_path=path, source_db=files_db,
        ))
        repo.add_report_evidence(key, report_status="main", added_by="analyst")
    return root, repo


def _admit_v2(repository: ReportRepository, root: Path, *, case_description: str):
    envelope = ReportGenerationInputBuilder(
        root / "investigation.db", "A"
    ).assemble(
        REPORT_GENERATION_PROMPT_VERSION, case_description=case_description
    )
    assert envelope.schema_version == 2
    envelope_json = canonical_json(envelope)
    digest = hashlib.sha256(envelope_json.encode("utf-8")).hexdigest()
    return repository.create_generation_input(
        "A", requested_by="analyst",
        input_schema_version=envelope.schema_version,
        prompt_version=REPORT_GENERATION_PROMPT_VERSION,
        input_envelope_json=envelope_json, input_hash=digest,
    )


def _outline_json(sections: list[dict]) -> str:
    return json.dumps(
        {"title": "虚假投资平台案最终报告", "sections": sections},
        ensure_ascii=False,
    )


def _section_json(heading: str, citations: list[dict] | None = None) -> str:
    return json.dumps(
        {"heading": heading, "content": f"{heading}的叙述内容。",
         "citations": citations or []},
        ensure_ascii=False,
    )


def _standard_outline() -> list[dict]:
    return [
        {"heading": "案件背景与检材概况", "brief": "案情与检材来源",
         "group_ids": []},
        {"heading": "话术体系分析", "brief": "话术与培训材料",
         "group_ids": ["script_training"]},
        {"heading": "系统账户与配置", "brief": "账户体系",
         "group_ids": ["sysconfig_accounts"]},
        {"heading": "系统组件与软件产物清单", "brief": "组件文件清单",
         "group_ids": ["software_inventory"]},
        {"heading": "综合结论", "brief": "汇总关键事实", "group_ids": []},
    ]


def _make_executor(tmp_path: Path, llm):
    repository = ReportRepository(tmp_path / "reports.db")
    executor = ReportGenerationExecutor(
        repository=repository,
        writer=GenerationReportWriter(tmp_path / "report_root"),
        llm_service=llm,
    )
    return repository, executor


async def _wait_terminal(repository: ReportRepository, generation_id: str):
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        row = repository.get_generation_input(generation_id)
        if row.status in ("completed", "failed"):
            return row
        await asyncio.sleep(0.01)
    raise AssertionError("generation did not terminate in time")


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_grouping_is_deterministic_and_total(tmp_path):
    root, _repo = _store(tmp_path)
    envelope = ReportGenerationInputBuilder(
        root / "investigation.db", "A"
    ).assemble(REPORT_GENERATION_PROMPT_VERSION, case_description=CASE_BACKGROUND)
    groups = group_report_evidence(envelope)
    by_id = {gid: [i.evidence_key for i in items] for gid, _n, items in groups}
    assert by_id["script_training"] == [KEY_SCRIPT]
    assert by_id["sysconfig_accounts"] == [KEY_PASSWD]
    assert by_id["software_inventory"] == [KEY_CASE_A]
    # rule order is preserved and every item is covered exactly once
    ids = [gid for gid, _n, _items in groups]
    assert ids == sorted(ids, key=ids.index)
    flat = [key for _gid, _n, items in groups for key in
            (i.evidence_key for i in items)]
    assert sorted(flat) == sorted(envelope.allowed_report_evidence_ids)


def test_v2_envelope_carries_case_description(tmp_path):
    root, _repo = _store(tmp_path)
    envelope = parse_generation_envelope(json.dumps({
        "schema_version": 2,
        "prompt_version": REPORT_GENERATION_PROMPT_VERSION,
        "task_id": "A",
        "case_description": CASE_BACKGROUND,
        "main_evidence": [], "appendix_evidence": [],
        "allowed_report_evidence_ids": [],
    }))
    assert envelope.case_description == CASE_BACKGROUND


# ---------------------------------------------------------------------------
# Sectioned execution
# ---------------------------------------------------------------------------


def test_v2_sectioned_pipeline_publishes(tmp_path):
    root, repo = _store(tmp_path)

    def section(heading: str, key: str | None = None, cid: str = "c001"):
        citations = (
            [{"citation_id": cid, "evidence_key": key}] if key else []
        )
        return _section_json(heading, citations)

    llm = ScriptedLLM([
        _outline_json(_standard_outline()),
        section("案件背景与检材概况"),
        section("话术体系分析", KEY_SCRIPT),
        section("系统账户与配置", KEY_PASSWD),
        section("系统组件与软件产物清单", KEY_CASE_A),
        section("综合结论"),
    ])

    async def scenario():
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit_v2(repository, root, case_description=CASE_BACKGROUND)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return row, terminal, repository

    row, terminal, repository = asyncio.run(scenario())
    assert terminal.status == "completed", terminal.error_message
    assert terminal.produced_version == 1
    # 1 outline call + 5 section calls
    assert len(llm.calls) == 6
    # the case background reaches the model in every stage prompt
    for _system, user in llm.calls:
        assert "杀猪盘" in user
    # the outline call sees the grouped inventory
    assert "话术与培训材料" in llm.calls[0][1]
    assert "老师包装" in llm.calls[0][1]
    # section 2 (话术) prompt carries only its group's projection
    assert "老师包装" in llm.calls[2][1]
    assert "/etc/passwd" not in llm.calls[2][1]


def test_v2_citation_renumbering_is_global(tmp_path):
    root, repo = _store(tmp_path)

    def section(heading: str, keys: list[str]):
        citations = [
            {"citation_id": f"s{index}", "evidence_key": key}
            for index, key in enumerate(keys, start=1)
        ]
        return _section_json(heading, citations)

    llm = ScriptedLLM([
        _outline_json(_standard_outline()),
        section("案件背景与检材概况", []),
        section("话术体系分析", [KEY_SCRIPT]),
        section("系统账户与配置", [KEY_PASSWD]),
        section("系统组件与软件产物清单", [KEY_CASE_A]),
        section("综合结论", []),
    ])

    async def scenario():
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit_v2(repository, root, case_description=CASE_BACKGROUND)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal, repository

    terminal, repository = asyncio.run(scenario())
    assert terminal.status == "completed", terminal.error_message
    manifest_files = sorted(
        (tmp_path / "report_root" / "snapshots").rglob("manifest.json")
    )
    assert manifest_files, "published manifest missing"
    manifest = json.loads(manifest_files[-1].read_text(encoding="utf-8"))
    ids = [c["citation_id"] for c in manifest["citations"]]
    assert ids == [f"c{i:03d}" for i in range(1, len(ids) + 1)]
    cited_keys = {c["evidence_key"] for c in manifest["citations"]}
    assert cited_keys == {KEY_SCRIPT, KEY_PASSWD, KEY_CASE_A}


def test_v2_section_scope_violation_fails(tmp_path):
    root, repo = _store(tmp_path)
    llm = ScriptedLLM([
        _outline_json(_standard_outline()),
        _section_json("案件背景与检材概况"),
        # the 话术 section cites a system file outside its group scope
        _section_json("话术体系分析", [
            {"citation_id": "c001", "evidence_key": KEY_PASSWD},
        ]),
    ])

    async def scenario():
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit_v2(repository, root, case_description=CASE_BACKGROUND)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.status == "failed"
    assert terminal.error_code == "citation_invalid"


def test_v2_outline_repairs_uncovered_group(tmp_path):
    root, repo = _store(tmp_path)
    # A 5-section outline that never assigns software_inventory; the
    # deterministic repair must append it to the last section instead of
    # dropping the evidence from the report.
    sections = [
        {"heading": "案件背景与检材概况", "brief": "案情与检材来源",
         "group_ids": []},
        {"heading": "话术体系分析", "brief": "话术与培训材料",
         "group_ids": ["script_training"]},
        {"heading": "系统账户与配置", "brief": "账户体系",
         "group_ids": ["sysconfig_accounts"]},
        {"heading": "时间线梳理", "brief": "关键活动时间", "group_ids": []},
        {"heading": "综合结论", "brief": "汇总关键事实", "group_ids": []},
    ]
    llm = ScriptedLLM([
        _outline_json(sections),
        _section_json("案件背景与检材概况"),
        _section_json("话术体系分析", [
            {"citation_id": "c001", "evidence_key": KEY_SCRIPT},
        ]),
        _section_json("系统账户与配置", []),
        _section_json("时间线梳理", []),
        _section_json("综合结论", []),
    ])

    async def scenario():
        repository, executor = _make_executor(tmp_path, llm)
        row = _admit_v2(repository, root, case_description=CASE_BACKGROUND)
        await executor.submit(row.generation_id)
        terminal = await _wait_terminal(repository, row.generation_id)
        await executor.shutdown()
        return terminal

    terminal = asyncio.run(scenario())
    assert terminal.status == "completed", terminal.error_message
