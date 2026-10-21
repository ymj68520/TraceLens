"""Stage narrative composition: validated directions woven into chapters."""
import json

import pytest

from httpserver.services.forensic_report.generation_prompts import STAGE_NARRATIVE_SYSTEM_V1
from httpserver.services.forensic_report.generation_sources import material
from httpserver.services.forensic_report.generation_stages import (
    compose_stage_narrative, render_stage_report, stage_citation_name,
)
from httpserver.services.forensic_report.models import (
    InvestigationDirection, MaterialSpan,
)


class _Env:
    """Read-model stub: only fields the composer/renderer touch."""
    def __init__(self, mode="evidence_only"):
        self.analysis_mode = mode
        self.case_description = "" if mode == "evidence_only" else "案情语境"
        self.evidence_scope_hash = "0" * 64
        self.baseline = None


def _envelope(mode="evidence_only"):
    return _Env(mode)


def _materials():
    return (
        material("m001", "file:/case/话术/7要素.docx", kind="text", status="ready",
                 text="培训话术正文片段"),
        material("m002", "file:/case/账目.xlsx", kind="text", status="ready",
                 text="转账记录摘录"),
    )


def _directions():
    quote = MaterialSpan(material_id="m001", quote="培训话术正文片段", character_start=0,
                         character_end=8, ambiguous=False)
    return (
        InvestigationDirection(
            direction_id="d1", title="话术培训材料", description="材料包含话术培训文档。",
            finding_kind="observation", supporting_refs=(quote,), counter_refs=(),
            missing_information=("材料原始来源",), alternative_explanations=(),
            baseline_direction_ids=(), case_context_quote="", origin="material",
        ),
    )


class NarrativeModel:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    async def chat_completion(self, system, user, **kwargs):
        self.calls.append(system)
        assert system == STAGE_NARRATIVE_SYSTEM_V1
        body = json.loads(user)
        assert body["validated_directions"][0]["supporting"][0]["file"] == "7要素.docx"
        return {"content": json.dumps(self.payload, ensure_ascii=False), "model": "synthetic"}


@pytest.mark.asyncio
async def test_narrative_sections_render_with_filename_citations():
    payload = {"sections": [
        {"heading": "检材范围与构成",
         "content": "本轮共读取两份冻结材料。其中 7要素.docx 为话术培训类文档，账目.xlsx 为账目摘录，"
                    "两者均通过来源哈希校验后进入本轮研判，未使用历史 AI 摘要替代原文。"},
        {"heading": "异常与待核线索",
         "content": "话术培训文档 7要素.docx 出现在窝点镜像中，其用途与流转链条仍需核对原件；账目文件账目.xlsx 中的"
                    "资金记录尚未与具体账户建立归属关系。上述两项仍缺原始来源信息，需人工调取完整文件核对。"},
    ]}
    model = NarrativeModel(payload)
    sections = await compose_stage_narrative(_envelope(), _materials(), _directions(), (), model)
    assert sections and sections[0]["heading"] == "检材范围与构成"

    response, _stage = render_stage_report(_envelope(), _materials(), _directions(), (), (), sections)
    headings = [s.heading for s in response.sections]
    assert "检材范围与构成" in headings and "材料自主发现" not in "".join(headings)
    body = next(s for s in response.sections if s.heading == "检材范围与构成")
    assert "c001" in body.citation_ids and "c002" in body.citation_ids
    clue = next(s for s in response.sections if s.heading == "异常与待核线索")
    assert clue.citation_ids == ("c001", "c002")
    assert response.sections[-1].heading == "人工核查建议"


@pytest.mark.asyncio
async def test_invalid_narrative_payload_returns_none_and_fragment_fallback():
    model = NarrativeModel({"sections": [{"heading": "x", "content": "短"}]})
    assert await compose_stage_narrative(_envelope(), _materials(), _directions(), (), model) is None

    response, _stage = render_stage_report(_envelope(), _materials(), _directions(), (), (), None)
    assert any(s.heading.startswith("材料自主发现") for s in response.sections)


def test_citation_name_handles_flat_and_nested_paths():
    assert stage_citation_name("file:/话术/7要素.docx") == "7要素.docx"
    assert stage_citation_name("file:README.txt") == "README.txt"
