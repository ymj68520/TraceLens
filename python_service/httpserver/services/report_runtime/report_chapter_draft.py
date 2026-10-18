"""ChapterDraftV1 / ReportAssertionV1 output contract (P7B §12-§14).

The Writer never returns free-form Markdown: the draft is born as
structured assertions.  ``assertion_id`` is server-derived deterministic
(§14) — never an LLM UUID, never an array index.  Duplicate semantic
assertions inside one chapter are a validation error (no two identities
for the same statement).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sha256_hex

CHAPTER_DRAFT_VERSION = "chapter-draft:v1"

AssertionClass = Literal["FACT", "INFERENCE", "HYPOTHESIS", "LIMITATION"]

BasisType = Literal[
    "accepted_finding",
    "accepted_event",
    "accepted_analysis",
    "direct_evidence",
    "report_assertion",  # synthesis only
    "chapter_digest",    # synthesis only
]


class ReportAssertionV1(BaseModel):
    """One atomic, auditable report assertion (§12).

    ``basis_refs`` = why the Writer may express this semantics;
    ``evidence_refs`` = the pack-visible evidence grounding it;
    ``citation_refs`` = the subset of evidence actually cited (§15/§17).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = ""
    text: str = Field(min_length=1, max_length=8000)

    assertion_class: AssertionClass
    basis_type: BasisType
    basis_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()

    input_context: str = ""  # generation input hash (bound by the draft)

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data["basis_refs"] = tuple(dict.fromkeys(data.get("basis_refs", ())))
        data["evidence_refs"] = tuple(
            dict.fromkeys(data.get("evidence_refs", ()))
        )
        data["citation_refs"] = tuple(
            dict.fromkeys(data.get("citation_refs", ()))
        )
        return data

    def with_identity(self, generation_input_hash: str) -> "ReportAssertionV1":
        """Server-derived deterministic assertion_id (§14): bound to the
        chapter generation input hash + normalized text + class + refs."""
        if self.input_context and self.input_context != generation_input_hash:
            raise ValueError("assertion already bound to another generation")
        payload = {
            "text": " ".join(self.text.split()),
            "assertion_class": self.assertion_class,
            "basis_type": self.basis_type,
            "basis_refs": list(self.basis_refs),
            "evidence_refs": list(self.evidence_refs),
            "citation_refs": list(self.citation_refs),
            "generation_input_hash": generation_input_hash,
        }
        digest = sha256_hex(payload)
        return self.model_copy(
            update={
                "assertion_id": "ras:" + digest[:24],
                "input_context": generation_input_hash,
            }
        )


class WriterMetadataV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = ""
    prompt_version: str
    narrative_policy_version: str
    generated_at: str


class ChapterDraftV1(BaseModel):
    """Strict structured Writer output (§12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_version: str = CHAPTER_DRAFT_VERSION

    chapter_id: str
    statements: tuple[ReportAssertionV1, ...] = Field(min_length=1)
    chapter_limitations: tuple[str, ...] = ()
    writer_metadata: WriterMetadataV1

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("draft_version", CHAPTER_DRAFT_VERSION)
        data["chapter_limitations"] = tuple(
            dict.fromkeys(data.get("chapter_limitations", ()))
        )
        return data

    @model_validator(mode="after")
    def _validate_duplicates(self):
        """§14: duplicate semantic assertions are an error, not a rewrite."""
        seen: set[tuple] = set()
        for statement in self.statements:
            key = (
                " ".join(statement.text.split()),
                statement.assertion_class,
                statement.basis_type,
            )
            if key in seen:
                raise ValueError(
                    "duplicate semantic assertion in chapter draft"
                )
            seen.add(key)
        return self

    def with_identities(self, generation_input_hash: str) -> "ChapterDraftV1":
        return self.model_copy(
            update={
                "statements": tuple(
                    statement.with_identity(generation_input_hash)
                    for statement in self.statements
                )
            }
        )

    def draft_hash(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


__all__ = [
    "AssertionClass",
    "BasisType",
    "CHAPTER_DRAFT_VERSION",
    "ChapterDraftV1",
    "ReportAssertionV1",
    "WriterMetadataV1",
]
