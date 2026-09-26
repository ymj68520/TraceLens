"""Report planning context, outline plan, validation, builders (P7A
§11-§16).

The frozen chain is:

    completed Investigation -> FinalizationRecord -> admission
    -> ReportPlanningContextV1 (frozen digests, one read transaction)
    -> ReportOutlinePlanV1 (versioned, immutable, validated)
    -> ChapterSpecV1 (report_chapter.py)

The planning context carries only digests and dispositions -- never full
evidence bodies, never review_pending semantic prose, never agent
reasoning (§11 forbidden list).  The outline validator fails closed on any
plan referencing unknown, unaccepted, or graph-identity material; callers
fall back to the deterministic outline builder (§13).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator

from ..evidence.exceptions import EvidenceStoreError
from ..investigation.repository import SUPPORTED_SCHEMA_VERSION
from .canonical import digest_text, sha256_hex
from .report_template import ReportTemplateDefinitionV1

PLANNING_CONTEXT_VERSION = "report-planning-context:v1"
OUTLINE_PLAN_VERSION = "report-outline-plan:v1"

OUTLINE_ID_PREFIX = "rout:"
PLANNING_CONTEXT_ID_PREFIX = "rpctx:"

PlannerKind = Literal["deterministic", "model_assisted", "analyst_modified"]

# §16: the closed review-status vocabulary a semantic basis may carry.
_ACCEPTED = "accepted"


# ---------------------------------------------------------------------------
# Frozen planning context (§11)
# ---------------------------------------------------------------------------


class FinalizationAnchorV1(BaseModel):
    """The immutable finalization anchor every plan is pinned to (§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finalization_id: str
    record_hash: str
    state_revision: int
    state_hash: str
    completion_mode: str


class AcceptedFindingDigestV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str
    assertion_class: str
    text_sha256: str
    evidence_refs: tuple[str, ...] = ()
    temporal_scope: Optional[dict] = None
    limitations_count: int = 0


class FindingReviewDigestV1(BaseModel):
    """Review-status vocabulary for validator decisions (§16/§24)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str
    status: str


class InvestigationEventDigestV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str  # "event:<event_id>@v<version>" — exact version pin (§23)
    event_id: str
    version: int
    title_sha256: str
    needs_refresh: bool = False


class AcceptedAnalysisDigestV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str  # analysis_id
    evidence_key: str
    version: int
    summary_sha256: str


class ReportEvidenceDigestV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_key: str
    report_status: str  # main / appendix (excluded never enters, §7)
    captured_at: Optional[int] = None
    has_bound_analysis: bool = False


class ReportPlanningContextV1(BaseModel):
    """Frozen digest-level planning input (§11).

    Set-like fields are canonically sorted before ``input_hash`` so equal
    semantic inputs hash identically (§62 replay discipline).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_version: str = PLANNING_CONTEXT_VERSION

    context_id: str
    task_id: str
    investigation_id: str

    finalization: FinalizationAnchorV1
    charter_digest: str

    required_question_dispositions: dict[str, str]
    coverage_dispositions: dict[str, str]
    limitations: tuple[str, ...] = ()
    completion_mode: str

    accepted_findings: tuple[AcceptedFindingDigestV1, ...] = ()
    finding_review_statuses: tuple[FindingReviewDigestV1, ...] = ()
    events: tuple[InvestigationEventDigestV1, ...] = ()
    accepted_analyses: tuple[AcceptedAnalysisDigestV1, ...] = ()
    report_evidence: tuple[ReportEvidenceDigestV1, ...] = ()

    template_id: str
    template_version: str
    template_hash: str

    input_hash: str
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        # freeze defaults into the payload before hashing so first-pass and
        # round-trip payloads are byte-identical
        data.setdefault("context_version", PLANNING_CONTEXT_VERSION)
        data["accepted_findings"] = sorted(
            (
                AcceptedFindingDigestV1.model_validate(item)
                for item in data.get("accepted_findings", ())
            ),
            key=lambda item: item.ref,
        )
        data["finding_review_statuses"] = sorted(
            (
                FindingReviewDigestV1.model_validate(item)
                for item in data.get("finding_review_statuses", ())
            ),
            key=lambda item: item.ref,
        )
        data["events"] = sorted(
            (
                InvestigationEventDigestV1.model_validate(item)
                for item in data.get("events", ())
            ),
            key=lambda item: item.ref,
        )
        data["accepted_analyses"] = sorted(
            (
                AcceptedAnalysisDigestV1.model_validate(item)
                for item in data.get("accepted_analyses", ())
            ),
            key=lambda item: item.ref,
        )
        data["report_evidence"] = sorted(
            (
                ReportEvidenceDigestV1.model_validate(item)
                for item in data.get("report_evidence", ())
            ),
            key=lambda item: item.evidence_key,
        )
        data["limitations"] = tuple(sorted(set(data.get("limitations", ()))))
        data["required_question_dispositions"] = dict(
            sorted(data.get("required_question_dispositions", {}).items())
        )
        data["coverage_dispositions"] = dict(
            sorted(data.get("coverage_dispositions", {}).items())
        )
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("context_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["context_id"] = PLANNING_CONTEXT_ID_PREFIX + digest[:24]
        return data

    # -- closed lookups for the validator / retrieval planner -------------

    def finding_review_status(self, ref: str) -> Optional[str]:
        for item in self.finding_review_statuses:
            if item.ref == ref:
                return item.status
        return None

    def accepted_finding(self, ref: str) -> Optional[AcceptedFindingDigestV1]:
        for item in self.accepted_findings:
            if item.ref == ref:
                return item
        return None

    def accepted_event(self, ref: str) -> Optional[InvestigationEventDigestV1]:
        for item in self.events:
            if item.ref == ref:
                return item
        return None

    def accepted_analysis(self, ref: str) -> Optional[AcceptedAnalysisDigestV1]:
        for item in self.accepted_analyses:
            if item.ref == ref:
                return item
        return None

    def report_evidence_keys(self) -> tuple[str, ...]:
        return tuple(item.evidence_key for item in self.report_evidence)

    def evidence_anchor_vocabulary(self) -> frozenset[str]:
        """The closed evidence-ref vocabulary an outline may pin as
        anchors: report-selected evidence plus evidence refs grounded
        inside accepted findings / accepted analyses (§22/§38)."""
        vocabulary = set(self.report_evidence_keys())
        for finding in self.accepted_findings:
            vocabulary.update(finding.evidence_refs)
        for analysis in self.accepted_analyses:
            vocabulary.add(analysis.evidence_key)
        return frozenset(vocabulary)


class ReportPlanningContextError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReportPlanningContextBuilder:
    """Assemble the frozen planning context in one ro read transaction.

    Mirrors the R2 ``ReportGenerationInputBuilder`` discipline: mode=ro URI
    + ``PRAGMA query_only`` + schema-version gate + ONE explicit read
    transaction, so an analyst action committed mid-assembly can never
    yield a mixed-epoch context.
    """

    def __init__(self, investigation_db_path, task_id: str):
        self._db_path = Path(investigation_db_path)
        self._task_id = task_id

    def assemble(
        self,
        investigation_id: str,
        finalization_id: str,
        *,
        template: ReportTemplateDefinitionV1,
    ) -> ReportPlanningContextV1:
        try:
            with closing(self._connect()) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != SUPPORTED_SCHEMA_VERSION:
                    raise ReportPlanningContextError(
                        "store_unsupported",
                        "investigation store schema is unsupported",
                    )
                conn.execute("BEGIN")
                try:
                    return self._assemble_with_conn(
                        conn, investigation_id, finalization_id, template
                    )
                finally:
                    conn.execute("ROLLBACK")
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation store is unavailable"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{quote(str(self._db_path))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    # -- assembly (read-only, single transaction) --------------------------

    def _assemble_with_conn(
        self,
        conn: sqlite3.Connection,
        investigation_id: str,
        finalization_id: str,
        template: ReportTemplateDefinitionV1,
    ) -> ReportPlanningContextV1:
        investigation = conn.execute(
            "SELECT status FROM agent_investigations "
            "WHERE task_id = ? AND investigation_id = ?",
            [self._task_id, investigation_id],
        ).fetchone()
        if investigation is None:
            raise ReportPlanningContextError(
                "investigation_not_found",
                f"investigation not found: {investigation_id}",
            )
        if investigation["status"] != "completed":
            raise ReportPlanningContextError(
                "investigation_not_completed",
                "planning context requires a completed investigation "
                f"(current: {investigation['status']})",
            )

        record = conn.execute(
            "SELECT finalization_id, state_revision, state_hash, "
            "completion_mode, input_hash, question_dispositions_json, "
            "coverage_dispositions_json, limitations_json "
            "FROM agent_finalizations "
            "WHERE task_id = ? AND investigation_id = ?",
            [self._task_id, investigation_id],
        ).fetchone()
        if record is None or record["finalization_id"] != finalization_id:
            raise ReportPlanningContextError(
                "finalization_mismatch",
                "planning context requires the exact FinalizationRecord",
            )
        import json

        question_dispositions = json.loads(
            record["question_dispositions_json"]
        )
        coverage_dispositions = json.loads(
            record["coverage_dispositions_json"]
        )
        limitations = tuple(json.loads(record["limitations_json"]))

        accepted_findings: list[AcceptedFindingDigestV1] = []
        review_statuses: list[FindingReviewDigestV1] = []
        for row in conn.execute(
            "SELECT finding_id, assertion_class, text, evidence_refs_json, "
            "temporal_scope_json, limitations_json, status, input_hash "
            "FROM investigation_findings "
            "WHERE task_id = ? AND investigation_id = ? "
            "ORDER BY finding_row_id",
            [self._task_id, investigation_id],
        ):
            ref = row["finding_id"]
            review_statuses.append(
                FindingReviewDigestV1(ref=ref, status=row["status"])
            )
            if row["status"] != _ACCEPTED:
                continue
            accepted_findings.append(
                AcceptedFindingDigestV1(
                    ref=ref,
                    assertion_class=row["assertion_class"],
                    text_sha256=digest_text(row["text"]),
                    evidence_refs=tuple(
                        sorted(set(json.loads(row["evidence_refs_json"])))
                    ),
                    temporal_scope=(
                        json.loads(row["temporal_scope_json"])
                        if row["temporal_scope_json"]
                        else None
                    ),
                    limitations_count=len(
                        json.loads(row["limitations_json"] or "[]")
                    ),
                )
            )

        events: list[InvestigationEventDigestV1] = []
        for row in conn.execute(
            "SELECT e.event_id, v.version, v.title, e.needs_refresh "
            "FROM investigation_events e "
            "JOIN investigation_event_versions v "
            "  ON v.task_id = e.task_id AND v.event_id = e.event_id "
            " AND v.version = (SELECT MAX(v2.version) "
            "                  FROM investigation_event_versions v2 "
            "                  WHERE v2.task_id = e.task_id "
            "                    AND v2.event_id = e.event_id) "
            "WHERE e.task_id = ? ORDER BY e.event_id",
            [self._task_id],
        ):
            ref = f"event:{row['event_id']}@v{row['version']}"
            events.append(
                InvestigationEventDigestV1(
                    ref=ref,
                    event_id=row["event_id"],
                    version=row["version"],
                    title_sha256=digest_text(row["title"]),
                    needs_refresh=bool(row["needs_refresh"]),
                )
            )

        analyses: list[AcceptedAnalysisDigestV1] = []
        for row in conn.execute(
            "SELECT analysis_id, evidence_key, version, summary "
            "FROM secondary_analyses "
            "WHERE task_id = ? AND status = 'accepted' "
            "ORDER BY analysis_id",
            [self._task_id],
        ):
            analyses.append(
                AcceptedAnalysisDigestV1(
                    ref=row["analysis_id"],
                    evidence_key=row["evidence_key"],
                    version=row["version"],
                    summary_sha256=digest_text(row["summary"]),
                )
            )

        report_evidence: list[ReportEvidenceDigestV1] = []
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='report_evidence'"
        ).fetchone() is not None:
            for row in conn.execute(
                "SELECT r.evidence_key, r.report_status, r.analysis_id, "
                "s.captured_at FROM report_evidence r "
                "LEFT JOIN evidence_snapshots s "
                "  ON s.task_id = r.task_id "
                " AND s.evidence_key = r.evidence_key "
                "WHERE r.task_id = ? ORDER BY r.evidence_key",
                [self._task_id],
            ):
                if row["report_status"] not in ("main", "appendix"):
                    # §7: excluded stays excluded; it is an audit state.
                    continue
                report_evidence.append(
                    ReportEvidenceDigestV1(
                        evidence_key=row["evidence_key"],
                        report_status=row["report_status"],
                        captured_at=row["captured_at"],
                        has_bound_analysis=row["analysis_id"] is not None,
                    )
                )

        return ReportPlanningContextV1(
            task_id=self._task_id,
            investigation_id=investigation_id,
            finalization=FinalizationAnchorV1(
                finalization_id=record["finalization_id"],
                record_hash=record["input_hash"],
                state_revision=record["state_revision"],
                state_hash=record["state_hash"],
                completion_mode=record["completion_mode"],
            ),
            charter_digest=digest_text(investigation_id),
            required_question_dispositions={
                str(key): str(value.get("disposition", "unknown"))
                for key, value in question_dispositions.items()
            },
            coverage_dispositions={
                str(key): str(value.get("status", "unknown"))
                for key, value in coverage_dispositions.items()
            },
            limitations=limitations,
            completion_mode=record["completion_mode"],
            accepted_findings=tuple(accepted_findings),
            finding_review_statuses=tuple(review_statuses),
            events=tuple(events),
            accepted_analyses=tuple(analyses),
            report_evidence=tuple(report_evidence),
            template_id=template.template_id,
            template_version=template.template_version,
            template_hash=template.template_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Outline plan (§14-§16)
# ---------------------------------------------------------------------------


class OutlineChapterV1(BaseModel):
    """One chapter of an outline plan (structural, pre-ChapterSpec)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chapter_id: str
    title: str
    purpose: str = ""
    section_kind: Literal["stable_core", "dynamic"] = "stable_core"
    section_id: Optional[str] = None
    planning_basis_refs: tuple[str, ...] = ()
    ordering: int = 0

    @model_validator(mode="after")
    def _validate_identity(self):
        if not self.chapter_id or not self.title:
            raise ValueError("chapter chapter_id/title must not be empty")
        return self


class ReportOutlinePlanV1(BaseModel):
    """One immutable, versioned outline plan (§14).

    ``outline_id`` is derived from the semantic payload, so the same
    planning basis under the same template deterministically replays to
    the same identity (§62); an analyst edit creates a NEW version row
    with ``parent_outline_id`` — history is never overwritten (§15).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outline_version: str = OUTLINE_PLAN_VERSION

    outline_id: str
    outline_revision: int = 1

    task_id: str
    investigation_id: str
    finalization_id: str

    template_id: str
    template_version: str
    template_hash: str

    planning_context_id: str
    planning_context_hash: str

    chapters: tuple[OutlineChapterV1, ...] = ()
    planning_basis_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    planner_kind: PlannerKind
    planner_model: Optional[str] = None
    parent_outline_id: Optional[str] = None
    revision_reason: Optional[str] = None

    created_at: str
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("outline_version", OUTLINE_PLAN_VERSION)
        data.setdefault("outline_revision", 1)
        data["chapters"] = sorted(
            (
                OutlineChapterV1.model_validate(item)
                for item in data.get("chapters", ())
            ),
            key=lambda item: (item.ordering, item.chapter_id),
        )
        for index, chapter in enumerate(data["chapters"], start=1):
            if chapter.ordering == 0:
                data["chapters"][index - 1] = chapter.model_copy(
                    update={"ordering": index}
                )
        data["planning_basis_refs"] = tuple(
            sorted(set(data.get("planning_basis_refs", ())))
        )
        data["limitations"] = tuple(sorted(set(data.get("limitations", ()))))
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key
            not in (
                "outline_id",
                "created_at",
                "input_hash",
                "parent_outline_id",
                "revision_reason",
                "outline_revision",
                "planner_model",
            )
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["outline_id"] = OUTLINE_ID_PREFIX + digest[:24]
        return data


class OutlineValidationError(ValueError):
    """A plan violates the outline contract; the caller must fail closed
    and (for model output) fall back to the deterministic outline."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_outline_plan(
    plan: ReportOutlinePlanV1,
    context: ReportPlanningContextV1,
    template: ReportTemplateDefinitionV1,
) -> None:
    """Deterministic §16 validation of one outline plan against its
    frozen planning context and template.  Raises OutlineValidationError.
    """
    if plan.task_id != context.task_id or (
        plan.investigation_id != context.investigation_id
    ):
        raise OutlineValidationError(
            "identity_mismatch", "outline does not match the context case"
        )
    if plan.finalization_id != context.finalization.finalization_id:
        raise OutlineValidationError(
            "finalization_mismatch", "outline is pinned to another finalization"
        )
    if plan.planning_context_id != context.context_id or (
        plan.planning_context_hash != context.input_hash
    ):
        raise OutlineValidationError(
            "context_mismatch", "outline does not match its planning context"
        )
    if plan.template_id != template.template_id or (
        plan.template_version != template.template_version
        or plan.template_hash != template.template_hash
    ):
        raise OutlineValidationError(
            "template_mismatch", "outline does not match the template version"
        )

    # §16: every stable-core section appears exactly once, in order.
    core_ids = [section.section_id for section in template.stable_core]
    required_core = [
        section
        for section in template.stable_core
        if section.required
    ]
    chapter_section_ids = [
        chapter.section_id
        for chapter in plan.chapters
        if chapter.section_kind == "stable_core" and chapter.section_id
    ]
    for section in required_core:
        if section.section_id not in chapter_section_ids:
            raise OutlineValidationError(
                "missing_required_section",
                f"required section missing: {section.section_id}",
            )
    if len(set(chapter_section_ids)) != len(chapter_section_ids):
        raise OutlineValidationError(
            "duplicate_section", "a stable-core section appears twice"
        )
    # relative order of the core chapters follows the template
    ordered = [
        section_id
        for section_id in core_ids
        if section_id in chapter_section_ids
    ]
    if ordered != chapter_section_ids:
        raise OutlineValidationError(
            "section_order_invalid",
            "stable-core chapters must follow template ordering",
        )

    chapter_ids = [chapter.chapter_id for chapter in plan.chapters]
    if len(set(chapter_ids)) != len(chapter_ids) or not chapter_ids:
        raise OutlineValidationError(
            "chapter_ids_invalid", "chapter ids must be unique and non-empty"
        )
    orderings = [chapter.ordering for chapter in plan.chapters]
    if orderings != sorted(orderings) or len(set(orderings)) != len(orderings):
        raise OutlineValidationError(
            "ordering_invalid", "chapter orderings must be strictly increasing"
        )

    # §16/§23: semantic refs accepted-only; evidence anchors from the
    # closed vocabulary; graph ids never a semantic basis.
    evidence_vocabulary = context.evidence_anchor_vocabulary()
    for chapter in plan.chapters:
        for ref in chapter.planning_basis_refs:
            _validate_basis_ref(ref, context, evidence_vocabulary)
    for ref in plan.planning_basis_refs:
        _validate_basis_ref(ref, context, evidence_vocabulary)

    # dynamic chapters must respect the template policy (§10)
    dynamic = [
        chapter
        for chapter in plan.chapters
        if chapter.section_kind == "dynamic"
    ]
    policy = template.dynamic_chapter_policy
    if not policy.enabled and dynamic:
        raise OutlineValidationError(
            "dynamic_disabled", "template does not allow dynamic chapters"
        )
    if len(dynamic) > policy.max_chapters:
        raise OutlineValidationError(
            "dynamic_overflow", "too many dynamic chapters"
        )
    for chapter in dynamic:
        if chapter.section_id is not None:
            raise OutlineValidationError(
                "dynamic_section_id", "dynamic chapters have no section_id"
            )
        for ref in chapter.planning_basis_refs:
            if ref.startswith("finding:"):
                if context.finding_review_status(ref) != _ACCEPTED:
                    raise OutlineValidationError(
                        "dynamic_basis_unaccepted",
                        "dynamic chapters require accepted findings",
                    )
            elif ref.startswith("event:"):
                if context.accepted_event(ref) is None:
                    raise OutlineValidationError(
                        "dynamic_basis_unaccepted",
                        "dynamic chapters require pinned accepted events",
                    )
            else:
                raise OutlineValidationError(
                    "dynamic_basis_invalid",
                    "dynamic chapters are built from accepted findings "
                    "or pinned accepted events only",
                )


def _validate_basis_ref(
    ref: str, context: ReportPlanningContextV1, evidence_vocabulary: frozenset
) -> None:
    if ref.startswith("graph:") or ref.startswith("gm:") or (
        ref.startswith("gcand:")
    ):
        raise OutlineValidationError(
            "graph_ref_forbidden", "graph ids are never semantic basis"
        )
    if ref.startswith("finding:"):
        status = context.finding_review_status(ref)
        if status is None:
            raise OutlineValidationError(
                "unknown_basis_ref", f"unknown finding ref: {ref}"
            )
        if status != _ACCEPTED:
            raise OutlineValidationError(
                "semantic_ref_not_accepted",
                f"finding ref is not accepted: {ref} ({status})",
            )
        return
    if ref.startswith("event:"):
        if context.accepted_event(ref) is None:
            raise OutlineValidationError(
                "unknown_basis_ref", f"unknown event ref: {ref}"
            )
        return
    if ref.startswith("sa_"):
        if context.accepted_analysis(ref) is None:
            raise OutlineValidationError(
                "unknown_basis_ref", f"unknown analysis ref: {ref}"
            )
        return
    if ref.startswith("question:"):
        if ref[len("question:"):] not in context.required_question_dispositions:
            raise OutlineValidationError(
                "unknown_basis_ref", f"unknown question ref: {ref}"
            )
        return
    if ref.startswith("coverage:"):
        if ref[len("coverage:"):] not in context.coverage_dispositions:
            raise OutlineValidationError(
                "unknown_basis_ref", f"unknown coverage ref: {ref}"
            )
        return
    if ref.startswith("cluster:"):
        # cluster rows are legacy report-evidence keys, never generation
        # input (R2 §4.2) and not a P7A evidence vocabulary member.
        raise OutlineValidationError(
            "evidence_ref_unknown", f"cluster refs are not report anchors: {ref}"
        )
    if ref in evidence_vocabulary:
        return
    raise OutlineValidationError(
        "evidence_ref_unknown", f"unknown evidence anchor: {ref}"
    )


# ---------------------------------------------------------------------------
# Deterministic default outline (§13)
# ---------------------------------------------------------------------------

DETERMINISTIC_OUTLINE_POLICY_VERSION = "report-outline-deterministic:v1"


class DeterministicReportOutlineBuilder:
    """Safe default outline from the frozen context + template (§13).

    The LLM planner is an organization enhancement, never a correctness
    requirement: this builder always works offline and its output passes
    :func:`validate_outline_plan` by construction.
    """

    policy_version = DETERMINISTIC_OUTLINE_POLICY_VERSION

    def build(
        self,
        context: ReportPlanningContextV1,
        template: ReportTemplateDefinitionV1,
    ) -> ReportOutlinePlanV1:
        chapters: list[OutlineChapterV1] = []
        basis_refs: list[str] = []
        ordering = 0
        insert_before = template.dynamic_chapter_policy.insert_before_section_id
        for section in template.stable_core:
            if (
                section.section_id == insert_before
                and template.dynamic_chapter_policy.enabled
            ):
                for finding in context.accepted_findings:
                    ordering += 1
                    chapters.append(
                        OutlineChapterV1(
                            chapter_id=f"dynamic_{finding.ref}",
                            title=f"调查发现：{finding.ref}",
                            purpose=(
                                "deterministic chapter for one accepted "
                                "finding"
                            ),
                            section_kind="dynamic",
                            planning_basis_refs=(finding.ref,),
                            ordering=ordering,
                        )
                    )
                    basis_refs.append(finding.ref)
            ordering += 1
            chapter_basis: tuple[str, ...] = ()
            if section.section_id == "investigation_findings":
                chapter_basis = tuple(
                    finding.ref for finding in context.accepted_findings
                )
                basis_refs.extend(chapter_basis)
            chapters.append(
                OutlineChapterV1(
                    chapter_id=f"core_{section.section_id}",
                    title=section.title,
                    purpose=f"stable core section {section.section_id}",
                    section_kind="stable_core",
                    section_id=section.section_id,
                    planning_basis_refs=chapter_basis,
                    ordering=ordering,
                )
            )
        return ReportOutlinePlanV1(
            task_id=context.task_id,
            investigation_id=context.investigation_id,
            finalization_id=context.finalization.finalization_id,
            template_id=template.template_id,
            template_version=template.template_version,
            template_hash=template.template_hash,
            planning_context_id=context.context_id,
            planning_context_hash=context.input_hash,
            chapters=tuple(chapters),
            planning_basis_refs=tuple(basis_refs),
            limitations=context.limitations,
            planner_kind="deterministic",
        )


__all__ = [
    "AcceptedAnalysisDigestV1",
    "AcceptedFindingDigestV1",
    "DETERMINISTIC_OUTLINE_POLICY_VERSION",
    "DeterministicReportOutlineBuilder",
    "FinalizationAnchorV1",
    "FindingReviewDigestV1",
    "InvestigationEventDigestV1",
    "OutlineChapterV1",
    "OutlineValidationError",
    "OUTLINE_PLAN_VERSION",
    "PLANNING_CONTEXT_VERSION",
    "ReportEvidenceDigestV1",
    "ReportOutlinePlanV1",
    "ReportPlanningContextBuilder",
    "ReportPlanningContextError",
    "ReportPlanningContextV1",
    "validate_outline_plan",
]
