"""Versioned Report Template starter registry (P7A §8-§10).

The architecture fixes only the template id
(``forensic_investigation_report``); its exact core sections, ordering and
narrative rules are explicitly TBD.  This module therefore provides a
*starter* registry: deterministic, versioned, and never presented as the
permanent architecture.  Templates distinguish the stable core from the
dynamic investigation chapters so a later template version can change
either without touching the contract.
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex

REPORT_TEMPLATE_CONTRACT_VERSION = "report-template-definition:v1"

FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID = "forensic_investigation_report"
TEMPLATE_STARTER_VERSION = "starter:v1"

GenerationMode = Literal["deterministic", "evidence_narrative", "synthesis"]


class ReportTemplateSectionV1(BaseModel):
    """One planned section slot of a template."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str
    title: str
    kind: Literal["stable_core", "dynamic"]
    generation_mode: GenerationMode
    required: bool
    ordering: int


class DynamicChapterPolicyV1(BaseModel):
    """How a template admits dynamic investigation chapters (§10).

    Dynamic chapters come from accepted investigation material (starter:
    accepted Findings), never one-per-evidence / one-per-playbook /
    one-per-specialist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    basis_kinds: tuple[str, ...] = ("accepted_finding",)
    max_chapters: int = 6
    insert_before_section_id: str = "limitations"


class ReportTemplateDefinitionV1(BaseModel):
    """One immutable versioned template definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = REPORT_TEMPLATE_CONTRACT_VERSION
    template_id: str
    template_version: str
    title: str
    stable_core: tuple[ReportTemplateSectionV1, ...] = ()
    dynamic_chapter_policy: DynamicChapterPolicyV1 = DynamicChapterPolicyV1()
    # §8: the architecture leaves section set / ordering / narrative rules
    # TBD; a starter template must say so instead of freezing by accident.
    narrative_rules_status: Literal["TBD"] = "TBD"
    notes: str = ""
    template_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("template_hash",)
        }
        payload["contract_version"] = REPORT_TEMPLATE_CONTRACT_VERSION
        data["template_hash"] = sha256_hex(payload)
        return data

    @model_validator(mode="after")
    def _validate_structure(self):
        if not self.template_id or not self.template_version:
            raise ValueError("template identity must not be empty")
        orderings = [section.ordering for section in self.stable_core]
        if orderings != list(range(1, len(orderings) + 1)):
            raise ValueError("stable core orderings must be contiguous 1..N")
        for section in self.stable_core:
            if section.kind != "stable_core":
                raise ValueError(
                    "stable_core list must contain stable_core sections"
                )
        return self


class ReportTemplateRegistry:
    """Deterministic lookup of immutable template versions."""

    def __init__(
        self,
        definitions: Iterable[ReportTemplateDefinitionV1] = (),
    ):
        self._templates: dict[tuple[str, str], ReportTemplateDefinitionV1] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ReportTemplateDefinitionV1) -> None:
        key = (definition.template_id, definition.template_version)
        if key in self._templates:
            raise ValueError(
                f"template version already registered: {key}"
            )
        self._templates[key] = definition

    def get(
        self, template_id: str, template_version: str
    ) -> Optional[ReportTemplateDefinitionV1]:
        return self._templates.get((template_id, template_version))

    def starter(self) -> ReportTemplateDefinitionV1:
        definition = self.get(
            FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
            TEMPLATE_STARTER_VERSION,
        )
        if definition is None:  # pragma: no cover - default registry
            raise LookupError("starter template is not registered")
        return definition


def build_starter_template() -> ReportTemplateDefinitionV1:
    """The starter ``forensic_investigation_report`` template (§9).

    Stable core mirrors the existing report structure; the mapping to
    generation modes follows the architecture (inventory/methodology/
    appendix -> deterministic, findings -> evidence_narrative).  Executive
    summary / conclusion chapters are synthesis-mode and only appear when a
    planning pass adds them -- the starter keeps the core minimal.
    """
    sections = (
        ReportTemplateSectionV1(
            section_id="case_overview",
            title="案件概述",
            kind="stable_core",
            generation_mode="deterministic",
            required=True,
            ordering=1,
        ),
        ReportTemplateSectionV1(
            section_id="scope_and_methodology",
            title="范围与方法",
            kind="stable_core",
            generation_mode="deterministic",
            required=True,
            ordering=2,
        ),
        ReportTemplateSectionV1(
            section_id="evidence_inventory",
            title="证据清单",
            kind="stable_core",
            generation_mode="deterministic",
            required=True,
            ordering=3,
        ),
        ReportTemplateSectionV1(
            section_id="investigation_findings",
            title="调查发现",
            kind="stable_core",
            generation_mode="evidence_narrative",
            required=True,
            ordering=4,
        ),
        ReportTemplateSectionV1(
            section_id="limitations",
            title="局限与说明",
            kind="stable_core",
            generation_mode="deterministic",
            required=True,
            ordering=5,
        ),
        ReportTemplateSectionV1(
            section_id="appendix",
            title="附录",
            kind="stable_core",
            generation_mode="deterministic",
            required=False,
            ordering=6,
        ),
    )
    return ReportTemplateDefinitionV1(
        template_id=FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
        template_version=TEMPLATE_STARTER_VERSION,
        title="调查报告",
        stable_core=sections,
        dynamic_chapter_policy=DynamicChapterPolicyV1(),
        notes=(
            "starter registry: sections/ordering/narrative rules remain "
            "TBD in the architecture and may change in a later template "
            "version"
        ),
    )


def default_template_registry() -> ReportTemplateRegistry:
    return ReportTemplateRegistry([build_starter_template()])


__all__ = [
    "FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID",
    "GenerationMode",
    "REPORT_TEMPLATE_CONTRACT_VERSION",
    "TEMPLATE_STARTER_VERSION",
    "DynamicChapterPolicyV1",
    "ReportTemplateDefinitionV1",
    "ReportTemplateRegistry",
    "ReportTemplateSectionV1",
    "build_starter_template",
    "default_template_registry",
]
