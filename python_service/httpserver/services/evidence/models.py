"""Pydantic models for Evidence identity and resolution (Phase C1/C2).

These are the only structured representations of Evidence identity produced by
``parse_evidence_key`` / ``EvidenceResolver``. Field combinations are validated
(C1c) so a file evidence cannot carry cluster fields and vice versa.
"""

from __future__ import annotations

from typing import Literal, Optional, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ParsedEvidenceKey(BaseModel):
    """Structured identity parsed from an evidence_key string (no DB access).

    ``canonical_key`` is the normalized string form: inputs that are equivalent
    (e.g. backslash vs forward slash paths) collapse to the same canonical_key
    and therefore the same Evidence identity (C1a).
    """

    model_config = ConfigDict(frozen=True)

    evidence_type: Literal["file", "cluster", "android_artifact"]
    canonical_key: str

    # file
    normalized_path: Optional[str] = None
    # cluster (event_type is decoded, human-readable)
    version: Optional[str] = None
    unix_minute: Optional[int] = None
    event_type: Optional[str] = None
    artifact_task_id: Optional[str] = None
    result_set_id: Optional[str] = None
    artifact_kind: Optional[str] = None
    artifact_record_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "ParsedEvidenceKey":
        if self.evidence_type == "file":
            if self.normalized_path is None:
                raise ValueError("file evidence key requires normalized_path")
            if any(v is not None for v in (self.version, self.unix_minute, self.event_type,
                                            self.artifact_task_id, self.result_set_id,
                                            self.artifact_kind, self.artifact_record_id)):
                raise ValueError("file evidence key must not carry cluster fields")
        elif self.evidence_type == "cluster":
            if self.version is None or self.unix_minute is None or self.event_type is None:
                raise ValueError("cluster evidence key requires version/unix_minute/event_type")
            if self.normalized_path is not None:
                raise ValueError("cluster evidence key must not carry normalized_path")
            if any(v is not None for v in (self.artifact_task_id, self.result_set_id,
                                            self.artifact_kind, self.artifact_record_id)):
                raise ValueError("cluster evidence key must not carry Android fields")
        else:
            if any(v is None for v in (self.artifact_task_id, self.result_set_id,
                                       self.artifact_kind, self.artifact_record_id)):
                raise ValueError("Android artifact key requires task, result set, kind and record")
            if any(v is not None for v in (self.normalized_path, self.version,
                                            self.unix_minute, self.event_type)):
                raise ValueError("Android artifact key must not carry file/cluster fields")
        return self


class ResolvedEvidence(BaseModel):
    """An Evidence confirmed to exist within a specific task's databases.

    ``evidence_key`` is always the CANONICAL form. ``source_db`` is a
    server-internal field (excluded from serialization) carrying the resolved DB
    path for later Investigation use; it is NEVER accepted as client input.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    evidence_key: str  # canonical
    evidence_type: Literal["file", "cluster", "android_artifact"]

    # file
    normalized_path: Optional[str] = None
    # cluster (recomputed from the stable identity; never fabricated)
    version: Optional[str] = None
    unix_minute: Optional[int] = None
    event_type: Optional[str] = None
    cluster_start: Optional[int] = None
    cluster_end: Optional[int] = None
    event_count: Optional[int] = None
    representative_timestamp: Optional[int] = None
    result_set_id: Optional[str] = None
    artifact_kind: Optional[str] = None
    artifact_record_id: Optional[int] = None

    # server-internal only: never serialized, never client-supplied
    source_db: str = Field(exclude=True, default="")
    result_manifest: dict[str, Any] = Field(exclude=True, default_factory=dict)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ResolvedEvidence":
        if self.evidence_type == "file":
            if self.normalized_path is None:
                raise ValueError("file evidence requires normalized_path")
            if any(v is not None for v in (
                self.version, self.unix_minute, self.event_type,
                self.cluster_start, self.cluster_end, self.event_count,
                self.representative_timestamp,
                self.result_set_id, self.artifact_kind, self.artifact_record_id,
            )):
                raise ValueError("file evidence must not carry cluster fields")
        elif self.evidence_type == "cluster":
            if self.version is None or self.unix_minute is None or self.event_type is None:
                raise ValueError("cluster evidence requires version/unix_minute/event_type")
            if self.normalized_path is not None:
                raise ValueError("cluster evidence must not carry normalized_path")
            if any(v is not None for v in (self.result_set_id, self.artifact_kind, self.artifact_record_id)):
                raise ValueError("cluster evidence must not carry Android fields")
        else:
            if any(v is None for v in (self.result_set_id, self.artifact_kind, self.artifact_record_id)):
                raise ValueError("Android artifact evidence requires version and record identity")
            if any(v is not None for v in (
                self.normalized_path, self.version, self.unix_minute, self.event_type,
                self.cluster_start, self.cluster_end, self.event_count, self.representative_timestamp,
            )):
                raise ValueError("Android artifact evidence must not carry file/cluster identity")
        return self
