"""Deterministic, read-only projection for the Phase 4 report pipeline."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from .investigation_persistence import (
    get_investigation_db_path,
    select_effective_event_version,
)

DATASET_VERSION = "1"
READINESS_REPORT_READY = "report_ready"
READINESS_BLOCKED = "blocked"
READINESS_EXCLUDED = "excluded"
VALIDATION_VALID = "valid"
VALIDATION_BLOCKED = "blocked"

# Dataset-level readiness errors. Normal deterministic exclusions use the
# exclusion codes below and do not make a dataset blocked.
EVENT_NOT_CONFIRMED = "EVENT_NOT_CONFIRMED"
EVENT_CURRENT_VERSION_MISSING = "EVENT_CURRENT_VERSION_MISSING"
CLAIM_EVIDENCE_LINK_MISSING = "CLAIM_EVIDENCE_LINK_MISSING"
CLAIM_EVIDENCE_NOT_IN_REPORT_SET = "CLAIM_EVIDENCE_NOT_IN_REPORT_SET"
EVIDENCE_RESOLUTION_FAILED = "EVIDENCE_RESOLUTION_FAILED"
EVIDENCE_TASK_MISMATCH = "EVIDENCE_TASK_MISMATCH"
EVIDENCE_SNAPSHOT_NOT_FOUND = "EVIDENCE_SNAPSHOT_NOT_FOUND"
PINNED_ANALYSIS_NOT_FOUND = "PINNED_ANALYSIS_NOT_FOUND"
PINNED_ANALYSIS_NOT_ACCEPTED = "PINNED_ANALYSIS_NOT_ACCEPTED"
PINNED_ANALYSIS_EVIDENCE_MISMATCH = "PINNED_ANALYSIS_EVIDENCE_MISMATCH"
REPORT_EVIDENCE_INVALID_STATUS = "REPORT_EVIDENCE_INVALID_STATUS"
REPORT_EVIDENCE_DUPLICATE = "REPORT_EVIDENCE_DUPLICATE"

# These describe expected filtering, rather than malformed or incomplete
# report inputs.
EVENT_NOT_CURRENT_ACCEPTED_VERSION = "EVENT_NOT_CURRENT_ACCEPTED_VERSION"
CLAIM_NOT_ACCEPTED = "CLAIM_NOT_ACCEPTED"
CLAIM_EVENT_VERSION_MISMATCH = "CLAIM_EVENT_VERSION_MISMATCH"


class DatasetValidationError(BaseModel):
    """Machine-readable error attached to a dataset entity."""

    code: str
    severity: str = "error"
    entity_type: str
    entity_id: Optional[str] = None
    evidence_key: Optional[str] = None
    message: str


class DatasetExclusion(BaseModel):
    """Deterministic reason why an event or claim is not report eligible."""

    code: str
    entity_type: str
    entity_id: Optional[str] = None
    event_version_id: Optional[str] = None
    message: str


class ReportDatasetClaimEvidenceLink(BaseModel):
    evidence_key: str
    relation: str
    rationale: Optional[str] = None


class ReportDatasetClaim(BaseModel):
    claim_id: str
    event_version_id: str
    claim_type: str
    claim_text: str
    readiness: str
    exclusion_reasons: List[DatasetExclusion] = Field(default_factory=list)
    validation_errors: List[DatasetValidationError] = Field(default_factory=list)
    evidence_links: List[ReportDatasetClaimEvidenceLink] = Field(default_factory=list)


class ReportDatasetEvent(BaseModel):
    event_id: str
    event_version_id: Optional[str] = None
    title: str
    summary: Optional[str] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    claims: List[ReportDatasetClaim] = Field(default_factory=list)
    exclusion_reasons: List[DatasetExclusion] = Field(default_factory=list)
    validation_errors: List[DatasetValidationError] = Field(default_factory=list)


class ReportDatasetEvidence(BaseModel):
    evidence_key: str
    evidence_type: str
    report_status: Optional[str] = None
    analysis_id: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    pinned_analysis: Optional[Dict[str, Any]] = None


class DatasetValidation(BaseModel):
    status: str
    errors: List[DatasetValidationError] = Field(default_factory=list)
    warnings: List[DatasetValidationError] = Field(default_factory=list)


class ReportDataset(BaseModel):
    task_id: str
    dataset_version: str = DATASET_VERSION
    generated_at: str
    events: List[ReportDatasetEvent] = Field(default_factory=list)
    report_evidence: List[ReportDatasetEvidence] = Field(default_factory=list)
    validation: DatasetValidation
    report_dataset_hash: str

    def canonical_content_dict(self) -> Dict[str, Any]:
        """Return the stable content projection used for hashing."""
        payload = self.model_dump(mode="json", exclude_none=False)
        payload.pop("generated_at", None)
        payload.pop("report_dataset_hash", None)
        payload["events"] = sorted(
            payload.get("events", []),
            key=lambda event: (
                event.get("start_time") is None,
                event.get("start_time") if event.get("start_time") is not None else 0,
                event.get("event_id") or "",
            ),
        )
        for event in payload["events"]:
            event["claims"] = sorted(
                event.get("claims", []), key=lambda claim: claim.get("claim_id") or ""
            )
            event["exclusion_reasons"] = _sort_exclusions(
                event.get("exclusion_reasons", [])
            )
            event["validation_errors"] = _sort_errors(
                event.get("validation_errors", [])
            )
            for claim in event["claims"]:
                claim["evidence_links"] = sorted(
                    claim.get("evidence_links", []),
                    key=lambda link: (
                        link.get("evidence_key") or "",
                        link.get("relation") or "",
                    ),
                )
                claim["exclusion_reasons"] = _sort_exclusions(
                    claim.get("exclusion_reasons", [])
                )
                claim["validation_errors"] = _sort_errors(
                    claim.get("validation_errors", [])
                )
        payload["report_evidence"] = sorted(
            payload.get("report_evidence", []),
            key=lambda evidence: evidence.get("evidence_key") or "",
        )
        validation = payload.get("validation") or {}
        validation["errors"] = _sort_errors(validation.get("errors", []))
        validation["warnings"] = _sort_errors(validation.get("warnings", []))
        payload["validation"] = validation
        return payload

    def canonical_content_json(self) -> str:
        return json.dumps(
            self.canonical_content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_content_json().encode("utf-8")).hexdigest()

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def _sort_errors(errors: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        errors,
        key=lambda item: (
            item.get("code") or "",
            item.get("entity_id") or "",
            item.get("evidence_key") or "",
            item.get("message") or "",
        ),
    )


def _sort_exclusions(exclusions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        exclusions,
        key=lambda item: (
            item.get("code") or "",
            item.get("entity_id") or "",
            item.get("event_version_id") or "",
            item.get("message") or "",
        ),
    )


def _json_value(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _task_db_paths(task_info: Dict[str, Any]) -> Dict[str, str]:
    files_db = task_info.get("output_files_db") or ""
    events_db = task_info.get("output_events_db") or ""
    raw_db = task_info.get("output_raw_db") or ""
    if not raw_db and files_db:
        if files_db.endswith("_files.db"):
            raw_db = files_db[: -len("_files.db")] + "_raw.db"
        elif files_db.endswith("files.db"):
            raw_db = files_db[: -len("files.db")] + "raw.db"
    if not events_db and files_db:
        if files_db.endswith("_files.db"):
            events_db = files_db[: -len("_files.db")] + "_events.db"
        elif files_db.endswith("files.db"):
            events_db = files_db[: -len("files.db")] + "events.db"
    return {"files_db": files_db, "events_db": events_db, "raw_db": raw_db}


def _snapshot_projection(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "evidence_key": row["evidence_key"],
        "evidence_type": row["evidence_type"],
        "source_metadata": _json_value(row["source_metadata_json"], {}),
        "initial_description": row["initial_description"],
        "initial_summary": row["initial_summary"],
        "source_hash": row["source_hash"],
        "source_size": row["source_size"],
        "source_mtime": row["source_mtime"],
        "source_updated_at": row["source_updated_at"],
        "captured_at": row["captured_at"],
    }


def _analysis_projection(
    row: sqlite3.Row,
    claims: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "analysis_id": row["id"],
        "version": row["version"],
        "evidence_key": row["evidence_key"],
        "evidence_type": row["evidence_type"],
        "analysis_type": row["analysis_type"],
        "description": row["description"],
        "summary": row["summary"],
        "status": row["status"],
        "grounding_status": row["grounding_status"],
        "grounding_warnings": _json_value(row["grounding_warnings"], []),
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "input_hash": row["input_hash"],
        "input_evidence_refs": _json_value(row["input_evidence_refs"], []),
        "claims": claims,
    }


class ReportDatasetBuilder:
    """Build a ReportDataset without mutating investigation or source DBs."""

    def __init__(
        self,
        task_loader: Callable[[str], Awaitable[Dict[str, Any]]],
        evidence_resolver: Any,
    ):
        self._task_loader = task_loader
        self._evidence_resolver = evidence_resolver

    @staticmethod
    def _connect_readonly(db_path: Path) -> sqlite3.Connection:
        if not db_path.exists():
            raise RuntimeError(f"investigation database not found: {db_path}")
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    async def _resolve(self, task_id: str, evidence_key: str) -> Any:
        resolver = self._evidence_resolver
        result = resolver.resolve(task_id, evidence_key)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _error(
        code: str,
        entity_type: str,
        message: str,
        *,
        entity_id: Optional[str] = None,
        evidence_key: Optional[str] = None,
    ) -> DatasetValidationError:
        return DatasetValidationError(
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            evidence_key=evidence_key,
            message=message,
        )

    @staticmethod
    def _exclusion(
        code: str,
        entity_type: str,
        message: str,
        *,
        entity_id: Optional[str] = None,
        event_version_id: Optional[str] = None,
    ) -> DatasetExclusion:
        return DatasetExclusion(
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            event_version_id=event_version_id,
            message=message,
        )

    async def build(self, task_id: str) -> ReportDataset:
        task_info = await self._task_loader(task_id)
        paths = _task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        db_path = get_investigation_db_path(paths["files_db"])

        with self._connect_readonly(db_path) as conn:
            events = conn.execute(
                "SELECT * FROM investigation_events WHERE task_id = ? "
                "ORDER BY COALESCE(start_time, evidence_start_time, 0), id",
                (task_id,),
            ).fetchall()
            versions = conn.execute(
                "SELECT * FROM investigation_event_versions WHERE task_id = ? "
                "ORDER BY event_id, version, id",
                (task_id,),
            ).fetchall()
            claims = conn.execute(
                "SELECT * FROM event_claims WHERE task_id = ? "
                "ORDER BY event_id, created_at, id",
                (task_id,),
            ).fetchall()
            claim_ids = [row["id"] for row in claims]
            claim_refs: Dict[str, List[sqlite3.Row]] = {claim_id: [] for claim_id in claim_ids}
            if claim_ids:
                placeholders = ",".join("?" for _ in claim_ids)
                for row in conn.execute(
                    "SELECT claim_id, evidence_key, relation, rationale "
                    f"FROM event_claim_evidence WHERE claim_id IN ({placeholders}) "
                    "ORDER BY claim_id, evidence_key, relation",
                    claim_ids,
                ):
                    claim_refs[row["claim_id"]].append(row)
            report_rows = conn.execute(
                "SELECT * FROM report_evidence WHERE task_id = ? "
                "ORDER BY COALESCE(sort_order, 999999), created_at, evidence_key, id",
                (task_id,),
            ).fetchall()
            snapshots = {
                row["evidence_key"]: row
                for row in conn.execute(
                    "SELECT * FROM evidence_snapshots WHERE task_id = ? "
                    "ORDER BY evidence_key, id",
                    (task_id,),
                )
            }
            analyses = {
                row["id"]: row
                for row in conn.execute(
                    "SELECT * FROM evidence_analysis_versions WHERE task_id = ? "
                    "ORDER BY id",
                    (task_id,),
                )
            }
            analysis_claim_rows = conn.execute(
                "SELECT * FROM evidence_analysis_claims ORDER BY analysis_id, created_at, id"
            ).fetchall()
            analysis_claim_refs: Dict[str, List[Dict[str, Any]]] = {}
            if analysis_claim_rows:
                analysis_claim_ids = [row["id"] for row in analysis_claim_rows]
                placeholders = ",".join("?" for _ in analysis_claim_ids)
                refs = conn.execute(
                    "SELECT claim_id, evidence_key, relation, rationale "
                    f"FROM claim_evidence WHERE claim_id IN ({placeholders}) "
                    "ORDER BY claim_id, evidence_key, relation",
                    analysis_claim_ids,
                ).fetchall()
                refs_by_claim: Dict[str, List[Dict[str, Any]]] = {}
                for ref in refs:
                    refs_by_claim.setdefault(ref["claim_id"], []).append({
                        "evidence_key": ref["evidence_key"],
                        "relation": ref["relation"],
                        "rationale": ref["rationale"],
                    })
                for row in analysis_claim_rows:
                    analysis_claim_refs.setdefault(row["analysis_id"], []).append({
                        "claim_id": row["id"],
                        "claim_text": row["claim_text"],
                        "claim_type": row["claim_type"],
                        "grounding_status": row["grounding_status"],
                        "origin": row["origin"],
                        "confidence": row["confidence"],
                        "evidence_refs": refs_by_claim.get(row["id"], []),
                    })

        current_by_event: Dict[str, sqlite3.Row] = {}
        for event in events:
            current = select_effective_event_version(conn, task_id, event["id"])
            if current is not None and int(event["needs_refresh"] or 0) == 0:
                current_by_event[event["id"]] = current

        claims_by_event: Dict[str, List[sqlite3.Row]] = {}
        for claim in claims:
            claims_by_event.setdefault(claim["event_id"], []).append(claim)

        report_evidence: List[ReportDatasetEvidence] = []
        all_errors: List[DatasetValidationError] = []
        evidence_errors: Dict[str, List[DatasetValidationError]] = {}
        report_keys = {row["evidence_key"] for row in report_rows}
        duplicate_keys = {
            key for key in report_keys
            if sum(1 for row in report_rows if row["evidence_key"] == key) > 1
        }
        for key in sorted(duplicate_keys):
            error = self._error(
                REPORT_EVIDENCE_DUPLICATE,
                "report_evidence",
                f"Report Evidence contains duplicate rows for {key}.",
                entity_id=key,
                evidence_key=key,
            )
            all_errors.append(error)
            evidence_errors.setdefault(key, []).append(error)

        resolved_cache: Dict[str, Any] = {}
        for row in report_rows:
            key = row["evidence_key"]
            status = row["usage"]
            entry_errors: List[DatasetValidationError] = list(evidence_errors.get(key, []))
            if status not in ("main", "appendix"):
                error = self._error(
                    REPORT_EVIDENCE_INVALID_STATUS,
                    "report_evidence",
                    f"Report Evidence has invalid status {status!r}.",
                    entity_id=row["id"],
                    evidence_key=key,
                )
                entry_errors.append(error)
                all_errors.append(error)

            if key not in resolved_cache:
                try:
                    resolved_cache[key] = await self._resolve(task_id, key)
                except Exception as exc:  # resolver failures are dataset errors
                    resolved_cache[key] = exc
            resolved = resolved_cache[key]
            if isinstance(resolved, Exception) or resolved is None:
                error = self._error(
                    EVIDENCE_RESOLUTION_FAILED,
                    "evidence",
                    f"Evidence {key} cannot be resolved in task {task_id}.",
                    entity_id=key,
                    evidence_key=key,
                )
                entry_errors.append(error)
                all_errors.append(error)
            else:
                resolved_task_id = (
                    resolved.get("task_id")
                    if isinstance(resolved, dict)
                    else getattr(resolved, "task_id", None)
                )
                if resolved_task_id != task_id:
                    error = self._error(
                        EVIDENCE_TASK_MISMATCH,
                        "evidence",
                        f"Evidence {key} resolved to another task.",
                        entity_id=key,
                        evidence_key=key,
                    )
                    entry_errors.append(error)
                    all_errors.append(error)

            snapshot_row = snapshots.get(key)
            snapshot = _snapshot_projection(snapshot_row) if snapshot_row else None
            if snapshot is None:
                error = self._error(
                    EVIDENCE_SNAPSHOT_NOT_FOUND,
                    "evidence",
                    f"Evidence {key} has no immutable investigation snapshot.",
                    entity_id=key,
                    evidence_key=key,
                )
                entry_errors.append(error)
                all_errors.append(error)

            analysis_id = row["analysis_id"]
            pinned_analysis = None
            if analysis_id:
                analysis_row = analyses.get(analysis_id)
                if analysis_row is None:
                    error = self._error(
                        PINNED_ANALYSIS_NOT_FOUND,
                        "analysis",
                        f"Pinned analysis {analysis_id} was not found for this task.",
                        entity_id=analysis_id,
                        evidence_key=key,
                    )
                    entry_errors.append(error)
                    all_errors.append(error)
                elif analysis_row["status"] != "accepted":
                    error = self._error(
                        PINNED_ANALYSIS_NOT_ACCEPTED,
                        "analysis",
                        f"Pinned analysis {analysis_id} is not accepted.",
                        entity_id=analysis_id,
                        evidence_key=key,
                    )
                    entry_errors.append(error)
                    all_errors.append(error)
                elif (
                    analysis_row["evidence_key"] != key
                    or analysis_row["evidence_type"] != row["evidence_type"]
                ):
                    error = self._error(
                        PINNED_ANALYSIS_EVIDENCE_MISMATCH,
                        "analysis",
                        f"Pinned analysis {analysis_id} does not match report evidence {key}.",
                        entity_id=analysis_id,
                        evidence_key=key,
                    )
                    entry_errors.append(error)
                    all_errors.append(error)
                else:
                    pinned_analysis = _analysis_projection(
                        analysis_row,
                        analysis_claim_refs.get(analysis_id, []),
                    )

            if entry_errors:
                evidence_errors.setdefault(key, []).extend(
                    error for error in entry_errors if error not in evidence_errors.get(key, [])
                )
            report_evidence.append(
                ReportDatasetEvidence(
                    evidence_key=key,
                    evidence_type=row["evidence_type"],
                    report_status=status,
                    analysis_id=analysis_id,
                    snapshot=snapshot,
                    pinned_analysis=pinned_analysis,
                )
            )

        dataset_events: List[ReportDatasetEvent] = []
        for event in events:
            event_id = event["id"]
            current = current_by_event.get(event_id)
            event_exclusions: List[DatasetExclusion] = []
            if event["review_status"] != "confirmed":
                event_exclusions.append(self._exclusion(
                    EVENT_NOT_CONFIRMED,
                    "event",
                    f"Event {event_id} is not confirmed for reporting.",
                    entity_id=event_id,
                ))
            if current is None:
                event_exclusions.append(self._exclusion(
                    EVENT_CURRENT_VERSION_MISSING,
                    "event",
                    f"Event {event_id} has no accepted semantic version.",
                    entity_id=event_id,
                ))

            event_claims: List[ReportDatasetClaim] = []
            event_errors: List[DatasetValidationError] = []
            for claim in claims_by_event.get(event_id, []):
                refs = [
                    ReportDatasetClaimEvidenceLink(
                        evidence_key=ref["evidence_key"],
                        relation=ref["relation"],
                        rationale=ref["rationale"],
                    )
                    for ref in claim_refs.get(claim["id"], [])
                ]
                exclusions: List[DatasetExclusion] = []
                errors: List[DatasetValidationError] = []
                is_current = current is not None and claim["event_version_id"] == current["id"]
                if event_exclusions:
                    exclusions.extend(event_exclusions)
                if not is_current:
                    exclusions.append(self._exclusion(
                        CLAIM_EVENT_VERSION_MISMATCH,
                        "claim",
                        f"Claim {claim['id']} does not belong to the current "
                        "accepted Event Version.",
                        entity_id=claim["id"],
                        event_version_id=claim["event_version_id"],
                    ))
                if claim["status"] != "accepted":
                    exclusions.append(self._exclusion(
                        CLAIM_NOT_ACCEPTED,
                        "claim",
                        f"Claim {claim['id']} is not accepted.",
                        entity_id=claim["id"],
                        event_version_id=claim["event_version_id"],
                    ))

                candidate = not event_exclusions and is_current and claim["status"] == "accepted"
                if candidate and not refs:
                    errors.append(self._error(
                        CLAIM_EVIDENCE_LINK_MISSING,
                        "claim",
                        f"Accepted claim {claim['id']} has no evidence provenance.",
                        entity_id=claim["id"],
                    ))
                if candidate:
                    for ref in refs:
                        key = ref.evidence_key
                        if key not in report_keys:
                            errors.append(self._error(
                                CLAIM_EVIDENCE_NOT_IN_REPORT_SET,
                                "claim",
                                f"Accepted claim {claim['id']} cites evidence outside "
                                "the Report Evidence Set.",
                                entity_id=claim["id"],
                                evidence_key=key,
                            ))
                        errors.extend(evidence_errors.get(key, []))

                if errors:
                    readiness = READINESS_BLOCKED
                    event_errors.extend(errors)
                    all_errors.extend(error for error in errors if error not in all_errors)
                elif exclusions:
                    readiness = READINESS_EXCLUDED
                else:
                    readiness = READINESS_REPORT_READY

                event_claims.append(ReportDatasetClaim(
                    claim_id=claim["id"],
                    event_version_id=claim["event_version_id"],
                    claim_type=claim["claim_type"],
                    claim_text=claim["claim_text"],
                    readiness=readiness,
                    exclusion_reasons=exclusions,
                    validation_errors=errors,
                    evidence_links=refs,
                ))

            title = (current["title"] if current is not None else None) or event["title"]
            summary = (current["summary"] if current is not None else None)
            if summary is None:
                summary = event["summary"]
            dataset_events.append(ReportDatasetEvent(
                event_id=event_id,
                event_version_id=current["id"] if current is not None else None,
                title=title or "",
                summary=summary,
                start_time=event["start_time"],
                end_time=event["end_time"],
                claims=event_claims,
                exclusion_reasons=event_exclusions,
                validation_errors=event_errors,
            ))

        generated_at = datetime.now(timezone.utc).isoformat()
        validation = DatasetValidation(
            status=(
                VALIDATION_BLOCKED
                if any(error.severity == "error" for error in all_errors)
                else VALIDATION_VALID
            ),
            errors=all_errors,
            warnings=[],
        )
        dataset = ReportDataset(
            task_id=task_id,
            dataset_version=DATASET_VERSION,
            generated_at=generated_at,
            events=dataset_events,
            report_evidence=report_evidence,
            validation=validation,
            report_dataset_hash="",
        )
        dataset.report_dataset_hash = dataset.compute_hash()
        return dataset
