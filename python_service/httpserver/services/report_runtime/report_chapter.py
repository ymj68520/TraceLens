"""ChapterSpecV1 (P7A §17-§19).

One outline chapter becomes a versioned ``chapter-spec:v1`` row pinned to
its outline revision.  P7A only records the spec (mode, scopes, anchor
refs, policy refs); it never executes a Writer (§18/§27).

Synthesis chapters carry ``context_stage =
deferred_until_chapter_digests`` (§19): their real ContextPack is a P7B
concern, and P7A refuses to freeze a pack that pretends detailed-chapter
digests already exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex

CHAPTER_SPEC_VERSION = "chapter-spec:v1"

CHAPTER_SPEC_ID_PREFIX = "rchap:"

GenerationMode = Literal["deterministic", "evidence_narrative", "synthesis"]

ContextStage = Literal[
    "ready", "deferred_until_chapter_digests"
]

HYDRATION_DEPTH_REF = "report-hydration-policy:v1"
RETRIEVAL_BUDGET_REF = "report-retrieval-budget:v1"
NARRATIVE_POLICY_REF = "report-narrative-policy:TBD"


class ChapterSpecV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_version: str = CHAPTER_SPEC_VERSION

    chapter_id: str
    outline_id: str
    outline_revision: int
    outline_hash: str

    title: str
    purpose: str = ""

    generation_mode: GenerationMode
    context_stage: ContextStage = "ready"

    topic_scope: str = ""
    entity_scope: tuple[str, ...] = ()
    time_scope: Optional[dict] = None

    required_anchor_refs: tuple[str, ...] = ()
    optional_anchor_refs: tuple[str, ...] = ()

    required_question_refs: tuple[str, ...] = ()
    coverage_refs: tuple[str, ...] = ()

    target_evidence_roles: tuple[
        Literal["anchor", "supporting", "retrieved_context"], ...
    ] = ("anchor", "supporting")

    hydration_policy_ref: str = HYDRATION_DEPTH_REF
    retrieval_budget_ref: str = RETRIEVAL_BUDGET_REF
    narrative_policy_ref: str = NARRATIVE_POLICY_REF

    ordering: int

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("spec_version", CHAPTER_SPEC_VERSION)
        data.setdefault("context_stage", "ready")
        for field, default in (
            ("topic_scope", ""),
            ("purpose", ""),
            ("time_scope", None),
            ("entity_scope", ()),
            ("optional_anchor_refs", ()),
            ("required_question_refs", ()),
            ("coverage_refs", ()),
            ("target_evidence_roles", ("anchor", "supporting")),
            ("hydration_policy_ref", HYDRATION_DEPTH_REF),
            ("retrieval_budget_ref", RETRIEVAL_BUDGET_REF),
            ("narrative_policy_ref", NARRATIVE_POLICY_REF),
        ):
            data.setdefault(field, default)
        data["entity_scope"] = tuple(sorted(set(data.get("entity_scope", ()))))
        data["required_anchor_refs"] = tuple(
            sorted(set(data.get("required_anchor_refs", ())))
        )
        data["optional_anchor_refs"] = tuple(
            sorted(set(data.get("optional_anchor_refs", ())))
        )
        data["required_question_refs"] = tuple(
            sorted(set(data.get("required_question_refs", ())))
        )
        data["coverage_refs"] = tuple(
            sorted(set(data.get("coverage_refs", ())))
        )
        data["target_evidence_roles"] = tuple(
            dict.fromkeys(data.get("target_evidence_roles", ()))
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("input_hash", "created_at")
        }
        data["input_hash"] = sha256_hex(payload)
        return data

    @model_validator(mode="after")
    def _validate_modes(self):
        overlap = set(self.required_anchor_refs) & set(
            self.optional_anchor_refs
        )
        if overlap:
            raise ValueError(
                f"anchor refs cannot be both required and optional: "
                f"{sorted(overlap)}"
            )
        if self.generation_mode == "synthesis" and (
            self.context_stage != "deferred_until_chapter_digests"
        ):
            # §19: synthesis chapters must not pretend their full context
            # exists before detailed chapter digests do.
            raise ValueError(
                "synthesis chapters are deferred_until_chapter_digests"
            )
        return self


class ChapterSpecError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def chapter_specs_from_outline(
    plan,
) -> tuple[ChapterSpecV1, ...]:
    """Derive one ChapterSpec per outline chapter (§17).

    Modes follow the template mapping (§18): stable-core inventory /
    methodology / appendix sections are deterministic; the findings core
    and dynamic finding chapters are evidence_narrative.  A P7A outline
    cannot yet create synthesis chapters (their digests do not exist);
    the deterministic builder therefore never emits one, and a model-
    assisted outline that asks for synthesis gets the deferred context
    stage instead of a fake-complete pack.
    """
    mode_by_section = {
        "evidence_inventory": "deterministic",
        "scope_and_methodology": "deterministic",
        "appendix": "deterministic",
        "case_overview": "deterministic",
        "limitations": "deterministic",
        "investigation_findings": "evidence_narrative",
    }
    specs: list[ChapterSpecV1] = []
    for chapter in plan.chapters:
        if chapter.section_kind == "stable_core":
            mode = mode_by_section.get(chapter.section_id, "deterministic")
        else:
            mode = "evidence_narrative"
        if mode == "synthesis":
            # only reachable via a custom template; P7A marks it deferred
            context_stage: ContextStage = "deferred_until_chapter_digests"
        else:
            context_stage = "ready"
        required_anchors = tuple(
            ref
            for ref in chapter.planning_basis_refs
            if ref.startswith("finding:") or ref.startswith("event:")
        )
        optional_anchors = tuple(
            ref
            for ref in chapter.planning_basis_refs
            if ref not in required_anchors
        )
        specs.append(
            ChapterSpecV1(
                chapter_id=chapter.chapter_id,
                outline_id=plan.outline_id,
                outline_revision=plan.outline_revision,
                outline_hash=plan.input_hash,
                title=chapter.title,
                purpose=chapter.purpose,
                generation_mode=mode,
                context_stage=context_stage,
                required_anchor_refs=required_anchors,
                optional_anchor_refs=optional_anchors,
                ordering=chapter.ordering,
            )
        )
    return tuple(specs)


__all__ = [
    "CHAPTER_SPEC_VERSION",
    "ChapterSpecError",
    "ChapterSpecV1",
    "chapter_specs_from_outline",
    "HYDRATION_DEPTH_REF",
    "NARRATIVE_POLICY_REF",
    "RETRIEVAL_BUDGET_REF",
]
