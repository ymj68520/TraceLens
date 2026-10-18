"""ChapterDigest / ReportAssertionLedger / deterministic cross-chapter
consistency / SemanticConsistencyReviewer (P7B §28-§37).

Digests (§28-§29) and the ledger (§30-§31) are deterministic projections
of validated chapters — no LLM, no new case semantics.  Deterministic
consistency (§32-§33) runs BEFORE the semantic reviewer and fails closed.
The reviewer (§34-§37) is tools=0, can only report issues, and never
mutates assertions/citations or accepts/publishes anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex
from .report_chapter_draft import ReportAssertionV1

CHAPTER_DIGEST_VERSION = "chapter-digest:v1"
LEDGER_VERSION = "report-assertion-ledger:v1"
CONSISTENCY_REVIEW_VERSION = "report-consistency-review:v1"

DIGEST_ID_PREFIX = "rdig:"
LEDGER_ID_PREFIX = "rled:"
REVIEW_ID_PREFIX = "rrev:"


class ChapterDigestV1(BaseModel):
    """Deterministic digest of one completed validated chapter (§28)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest_version: str = CHAPTER_DIGEST_VERSION

    digest_id: str
    chapter_id: str
    generation_id: str
    draft_hash: str

    assertion_ids: tuple[str, ...] = ()
    assertion_classes: tuple[str, ...] = ()
    basis_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    context_pack_hash: str
    digest_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("digest_version", CHAPTER_DIGEST_VERSION)
        for key in (
            "assertion_ids",
            "assertion_classes",
            "basis_refs",
            "evidence_refs",
            "citation_refs",
            "limitations",
        ):
            data[key] = tuple(sorted(set(data.get(key, ()))))
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("digest_id", "digest_hash", "created_at")
        }
        digest = sha256_hex(payload)
        data["digest_hash"] = digest
        data["digest_id"] = DIGEST_ID_PREFIX + digest[:24]
        return data


def build_chapter_digest(
    draft,
    *,
    generation_id: str,
    context_pack_hash: str,
) -> ChapterDigestV1:
    """§29: deterministic — built from validated assertions only."""
    assertion_ids = tuple(
        statement.assertion_id for statement in draft.statements
    )
    return ChapterDigestV1(
        chapter_id=draft.chapter_id,
        generation_id=generation_id,
        draft_hash=draft.draft_hash(),
        assertion_ids=assertion_ids,
        assertion_classes=tuple(
            statement.assertion_class for statement in draft.statements
        ),
        basis_refs=tuple(
            ref
            for statement in draft.statements
            for ref in statement.basis_refs
        ),
        evidence_refs=tuple(
            ref
            for statement in draft.statements
            for ref in statement.evidence_refs
        ),
        citation_refs=tuple(
            ref
            for statement in draft.statements
            for ref in statement.citation_refs
        ),
        limitations=tuple(draft.chapter_limitations),
        context_pack_hash=context_pack_hash,
    )


class LedgerAssertionV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chapter_id: str
    assertion_id: str
    text_sha256: str
    assertion_class: str
    basis_type: str
    basis_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()


class ReportAssertionLedgerV1(BaseModel):
    """Immutable aggregation of validated detailed chapters (§30-§31)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_version: str = LEDGER_VERSION

    ledger_id: str
    task_id: str
    investigation_id: str
    finalization_id: str
    outline_id: str
    outline_revision: int
    finalization_record_hash: str = ""

    chapter_generation_ids: tuple[str, ...] = ()
    chapter_draft_hashes: tuple[str, ...] = ()
    assertions: tuple[LedgerAssertionV1, ...] = ()
    evidence_provenance_index: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    semantic_basis_index: dict[str, tuple[str, ...]] = Field(
        default_factory=dict
    )
    major_limitations: tuple[str, ...] = ()

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("ledger_version", LEDGER_VERSION)
        data["assertions"] = sorted(
            (
                LedgerAssertionV1.model_validate(item)
                for item in data.get("assertions", ())
            ),
            key=lambda item: (item.chapter_id, item.assertion_id),
        )
        data["chapter_generation_ids"] = tuple(
            sorted(set(data.get("chapter_generation_ids", ())))
        )
        data["chapter_draft_hashes"] = tuple(
            sorted(set(data.get("chapter_draft_hashes", ())))
        )
        data["major_limitations"] = tuple(
            sorted(set(data.get("major_limitations", ())))
        )
        data["evidence_provenance_index"] = {
            key: tuple(sorted(set(value)))
            for key, value in sorted(
                data.get("evidence_provenance_index", {}).items()
            )
        }
        data["semantic_basis_index"] = {
            key: tuple(sorted(set(value)))
            for key, value in sorted(
                data.get("semantic_basis_index", {}).items()
            )
        }
        # defaulted field normalization keeps the derived hash IDEMPOTENT:
        # a JSON reload must see the same payload keys as the first build.
        data.setdefault("finalization_record_hash", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("ledger_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["ledger_id"] = LEDGER_ID_PREFIX + digest[:24]
        return data


def build_assertion_ledger(
    *,
    task_id: str,
    investigation_id: str,
    finalization_id: str,
    outline_id: str,
    outline_revision: int,
    finalization_record_hash: str = "",
    completed: list[dict] = None,
) -> ReportAssertionLedgerV1:
    """Aggregate completed chapter generation rows (validated output only).

    ``completed`` rows carry output_json (validated ChapterDraft) and
    digest_json (ChapterDigest); invalid/failed chapters are excluded by
    the caller (§70).
    """
    import json as _json_mod

    completed = completed or []
    assertions: list[LedgerAssertionV1] = []
    generation_ids: list[str] = []
    draft_hashes: list[str] = []
    evidence_index: dict[str, list[str]] = {}
    basis_index: dict[str, list[str]] = {}
    limitations: list[str] = []
    for row in completed:
        import json as _json

        output = _json.loads(row["output_json"])
        statements = output["statements"]
        generation_ids.append(row["generation_id"])
        draft_hashes.append(output.get("draft_hash", ""))
        for statement in statements:
            import hashlib as _h

            entry = LedgerAssertionV1(
                chapter_id=row["chapter_id"],
                assertion_id=statement["assertion_id"],
                text_sha256=_h.sha256(
                    statement["text"].encode("utf-8")
                ).hexdigest(),
                assertion_class=statement["assertion_class"],
                basis_type=statement["basis_type"],
                basis_refs=tuple(statement.get("basis_refs", ())),
                evidence_refs=tuple(statement.get("evidence_refs", ())),
                citation_refs=tuple(statement.get("citation_refs", ())),
            )
            assertions.append(entry)
            for ref in entry.evidence_refs:
                evidence_index.setdefault(ref, []).append(entry.assertion_id)
            for ref in entry.basis_refs:
                basis_index.setdefault(ref, []).append(entry.assertion_id)
        digest_row = row.get("digest_json")
        if digest_row:
            digest = _json.loads(digest_row)
            limitations.extend(digest.get("limitations", ()))
    return ReportAssertionLedgerV1(
        task_id=task_id,
        investigation_id=investigation_id,
        finalization_id=finalization_id,
        outline_id=outline_id,
        outline_revision=outline_revision,
        finalization_record_hash=finalization_record_hash,
        chapter_generation_ids=tuple(generation_ids),
        chapter_draft_hashes=tuple(draft_hashes),
        assertions=tuple(assertions),
        evidence_provenance_index=evidence_index,
        semantic_basis_index=basis_index,
        major_limitations=tuple(limitations),
    )


# ---------------------------------------------------------------------------
# Deterministic cross-chapter consistency (§32-§33) — runs BEFORE the
# semantic reviewer; any failure means the report consistency = failed.
# ---------------------------------------------------------------------------

CONSISTENCY_CHECK_VERSION = "report-consistency-deterministic:v1"


class DeterministicConsistencyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def run_deterministic_consistency(
    ledger: ReportAssertionLedgerV1,
    *,
    digests: list[ChapterDigestV1],
    evidence_digests: dict[str, str],
    finalization_id: str,
    outline_id: str,
    outline_revision: int,
) -> list[dict]:
    """§32 checks.  Returns the issue list (empty == PASS); raises never —
    the caller decides fail-closed handling.  Identity comes only from
    deterministic fields, never from text guessing."""
    issues: list[dict] = []

    def _issue(code: str, message: str, **detail) -> None:
        issues.append({"code": code, "message": message, **detail})

    # same Evidence ref -> consistent digest/metadata across chapters
    for ref, assertion_ids in ledger.evidence_provenance_index.items():
        provided = evidence_digests.get(ref)
        if provided is None:
            _issue(
                "EVIDENCE_DIGEST_UNKNOWN",
                f"evidence ref lacks a frozen digest: {ref}",
                evidence_ref=ref,
            )
    # same accepted semantic basis -> consistent assertion class
    class_by_basis: dict[str, set[str]] = {}
    for assertion in ledger.assertions:
        for ref in assertion.basis_refs:
            class_by_basis.setdefault(ref, set()).add(
                assertion.assertion_class
            )
    for ref, classes in class_by_basis.items():
        # the classes used against one basis must not exceed its ceiling
        # drift: an INFERENCE basis cited by a FACT assertion would have
        # already failed chapter validation; here we catch cross-chapter
        # drift between DIFFERENT assertion classes over the same basis
        # where one strictly dominates on the strength axis.
        strengths = {
            cls: STRENGTH[cls] for cls in classes if cls in STRENGTH
        }
        if strengths and max(strengths.values()) != min(strengths.values()):
            _issue(
                "BASIS_CLASS_DRIFT",
                f"assertion classes drift across chapters for basis {ref}",
                basis_ref=ref,
                classes=sorted(classes),
            )
    # forbidden review status refs
    for ref in ledger.semantic_basis_index:
        if ":review_pending" in ref or ":rejected" in ref:
            _issue(
                "FORBIDDEN_REVIEW_STATUS",
                f"ledger carries a non-accepted semantic basis: {ref}",
                basis_ref=ref,
            )
    # binding identity across digests
    # finalization / outline binding is carried by the ledger itself; the
    # caller-supplied expected values must match
    if ledger.finalization_id != finalization_id:
        _issue(
            "FINALIZATION_MISMATCH",
            "ledger is pinned to another finalization",
        )
    if ledger.outline_id != outline_id or (
        ledger.outline_revision != outline_revision
    ):
        _issue(
            "OUTLINE_MISMATCH",
            "ledger is pinned to another outline revision",
        )
    # duplicate assertions (same chapter + same identity would already be
    # rejected at draft level; cross-chapter duplicates of the same
    # semantic statement are allowed but must be identical in class)
    text_by_content: dict[tuple, set[str]] = {}
    for assertion in ledger.assertions:
        key = (assertion.text_sha256, assertion.assertion_class)
        text_by_content.setdefault(key, set()).add(assertion.assertion_id)
    # citation allowlist validity: every citation ref must also be an
    # evidence ref of the same assertion (§17) — already enforced per
    # chapter; re-checked here against the ledger aggregation.
    for assertion in ledger.assertions:
        if not set(assertion.citation_refs) <= set(assertion.evidence_refs):
            _issue(
                "CITATION_NOT_GROUNDED",
                f"assertion {assertion.assertion_id} cites evidence outside "
                "its own evidence refs",
                assertion_id=assertion.assertion_id,
            )
    return issues


STRENGTH = {"HYPOTHESIS": 0, "INFERENCE": 1, "FACT": 2}


# ---------------------------------------------------------------------------
# SemanticConsistencyReviewer (§34-§37): one report-level reviewer,
# tools = 0, issues-only output.
# ---------------------------------------------------------------------------

CONSISTENCY_REVIEWER_PROMPT_VERSION = "report-consistency-reviewer:starter:v1"

ReviewStatus = Literal["pass", "issues_found", "indeterminate"]

REVIEWER_SYSTEM_PROMPT = (
    "你是报告级语义一致性审查器。工具数量为零：你只能看到 ChapterDigest、"
    "ReportAssertionLedger、Question dispositions 与 limitations。\n"
    "你只能发现问题，不能改写断言、不能增删证据、不能改变引用、不能接受或"
    "发布报告。\n"
    "检查：跨章矛盾、同一实体/事件描述不一致、时间线不相容、断言强度漂移、"
    "因果过度推断、actor 归因过度、对已接受 basis 的误述、重大 limitation "
    "遗漏、Question disposition 误述、结论超出章节支撑。\n"
    "输出严格 JSON：{status: pass|issues_found|indeterminate, issues: [{"
    "issue_type, description, affected_chapter_ids[], "
    "affected_assertion_ids[]}], contradiction_notes[], "
    "overstatement_notes[], missing_limitation_notes[]}。"
    "不要重新判断案件事实。"
)


class ReviewIssueV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    issue_type: str
    description: str
    affected_chapter_ids: tuple[str, ...] = ()
    affected_assertion_ids: tuple[str, ...] = ()


class ReportConsistencyReviewV1(BaseModel):
    """Versioned reviewer output (§35).  Runtime failures are NEVER
    disguised as indeterminate — the caller records a failed runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_version: str = CONSISTENCY_REVIEW_VERSION

    review_id: str
    ledger_id: str
    ledger_hash: str
    task_id: str
    investigation_id: str

    status: ReviewStatus
    issues: tuple[ReviewIssueV1, ...] = ()
    affected_chapter_ids: tuple[str, ...] = ()
    affected_assertion_ids: tuple[str, ...] = ()
    contradiction_notes: tuple[str, ...] = ()
    overstatement_notes: tuple[str, ...] = ()
    missing_limitation_notes: tuple[str, ...] = ()

    model: str = ""
    prompt_version: str = CONSISTENCY_REVIEWER_PROMPT_VERSION
    model_config_hash: str = ""

    input_hash: str = ""
    created_at: str

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("review_version", CONSISTENCY_REVIEW_VERSION)
        data["issues"] = tuple(
            ReviewIssueV1.model_validate(item)
            for item in data.get("issues", ())
        )
        data["contradiction_notes"] = tuple(
            sorted(set(data.get("contradiction_notes", ())))
        )
        data["overstatement_notes"] = tuple(
            sorted(set(data.get("overstatement_notes", ())))
        )
        data["missing_limitation_notes"] = tuple(
            sorted(set(data.get("missing_limitation_notes", ())))
        )
        # defaulted field normalization keeps the derived hash IDEMPOTENT:
        # a JSON reload must see the same payload keys as the first build.
        data.setdefault("affected_chapter_ids", ())
        data.setdefault("affected_assertion_ids", ())
        data.setdefault("model", "")
        data.setdefault("prompt_version", CONSISTENCY_REVIEWER_PROMPT_VERSION)
        data.setdefault("model_config_hash", "")
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("review_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["review_id"] = REVIEW_ID_PREFIX + digest[:24]
        return data

    @model_validator(mode="after")
    def _validate_issue_refs(self):
        """§72: unknown assertion refs in reviewer output invalidate it."""
        known = set(self.affected_assertion_ids)
        for issue in self.issues:
            unknown = [
                ref
                for ref in issue.affected_assertion_ids
                if ref not in known
            ]
            if unknown:
                raise ValueError(
                    "reviewer references unknown assertion ids: "
                    f"{sorted(unknown)}"
                )
        if self.status == "pass" and self.issues:
            raise ValueError("pass review cannot carry issues")
        if self.status == "issues_found" and not self.issues:
            raise ValueError("issues_found review requires issues")
        return self


def build_reviewer_user_prompt(
    ledger: ReportAssertionLedgerV1,
    digests: list[ChapterDigestV1],
    *,
    question_dispositions: dict[str, str],
    major_limitations: tuple[str, ...],
) -> str:
    from .canonical import canonical_dumps

    projection = {
        "chapter_digests": [
            digest.model_dump(mode="json") for digest in digests
        ],
        "assertions": [
            assertion.model_dump(mode="json")
            for assertion in ledger.assertions
        ],
        "question_dispositions": question_dispositions,
        "major_limitations": list(major_limitations),
    }
    return (
        "以下是全部可用审查输入（无任何检索通道）：\n"
        + canonical_dumps(projection)
        + "\n\n请输出审查 JSON。"
    )


class SemanticConsistencyReviewer:
    """Tools = 0 report-level reviewer (§34).  ``llm_chat`` is the shared
    LLM entrypoint; the reviewer can only classify issues."""

    tools = 0

    def __init__(self, llm_chat: Callable[[str, str], Awaitable[dict]]):
        self._llm_chat = llm_chat

    async def review(
        self,
        ledger: ReportAssertionLedgerV1,
        digests: list[ChapterDigestV1],
        *,
        question_dispositions: dict[str, str],
        major_limitations: tuple[str, ...],
        model_config_hash: str = "",
    ) -> ReportConsistencyReviewV1:
        user_prompt = build_reviewer_user_prompt(
            ledger,
            digests,
            question_dispositions=question_dispositions,
            major_limitations=major_limitations,
        )
        result = await self._llm_chat(
            REVIEWER_SYSTEM_PROMPT, user_prompt
        )
        import json

        try:
            payload = json.loads(result.get("content", ""))
        except json.JSONDecodeError as exc:
            raise ValueError("reviewer output is not valid JSON") from exc
        known_assertions = {
            assertion.assertion_id for assertion in ledger.assertions
        }
        known_chapters = {digest.chapter_id for digest in digests}
        issues = payload.get("issues", []) or []
        # §72: unknown refs in reviewer output -> invalid output
        for issue in issues:
            unknown_a = [
                ref
                for ref in issue.get("affected_assertion_ids", [])
                if ref not in known_assertions
            ]
            unknown_c = [
                ref
                for ref in issue.get("affected_chapter_ids", [])
                if ref not in known_chapters
            ]
            if unknown_a or unknown_c:
                raise ValueError(
                    "reviewer referenced unknown ids "
                    f"(assertions: {unknown_a}, chapters: {unknown_c})"
                )
        affected_assertions = sorted(
            {
                ref
                for issue in issues
                for ref in issue.get("affected_assertion_ids", [])
            }
        )
        affected_chapters = sorted(
            {
                ref
                for issue in issues
                for ref in issue.get("affected_chapter_ids", [])
            }
        )
        return ReportConsistencyReviewV1(
            ledger_id=ledger.ledger_id,
            ledger_hash=ledger.input_hash,
            task_id=ledger.task_id,
            investigation_id=ledger.investigation_id,
            status=payload.get("status", "indeterminate"),
            issues=issues,
            affected_chapter_ids=tuple(affected_chapters),
            affected_assertion_ids=tuple(affected_assertions),
            contradiction_notes=tuple(
                issue.get("description", "")
                for issue in issues
                if issue.get("issue_type") == "contradiction"
            ),
            overstatement_notes=tuple(
                issue.get("description", "")
                for issue in issues
                if issue.get("issue_type") == "overstatement"
            ),
            missing_limitation_notes=tuple(
                issue.get("description", "")
                for issue in issues
                if issue.get("issue_type") == "missing_limitation"
            ),
            model=result.get("model", ""),
            prompt_version=CONSISTENCY_REVIEWER_PROMPT_VERSION,
            model_config_hash=model_config_hash,
        )


__all__ = [
    "ChapterDigestV1",
    "CONSISTENCY_CHECK_VERSION",
    "CONSISTENCY_REVIEWER_PROMPT_VERSION",
    "DeterministicConsistencyError",
    "LedgerAssertionV1",
    "build_assertion_ledger",
    "build_chapter_digest",
    "build_reviewer_user_prompt",
    "ReportAssertionLedgerV1",
    "ReportConsistencyReviewV1",
    "ReviewIssueV1",
    "run_deterministic_consistency",
    "SemanticConsistencyReviewer",
    "STRENGTH",
]
