"""Investigation Workbench service (二次调查分析工作台).

Orchestrates analyst-guided secondary analysis on top of the read-only initial
pipeline data (raw.db / events.db / files.db / Base KG). All investigation
state lives in the per-task ``investigation.db`` managed by
``investigation_persistence``.

Hard rules enforced here:
- Canonical evidence/cluster keys are defined in this module only.
- Evidence identity is (task_id, evidence_key); resolution never crosses tasks.
- Secondary analysis NEVER calls ``persist_to_files_db`` — the initial LLM
  description is immutable and snapshotted into ``evidence_snapshots``.
- LLM outputs are strictly validated; evidence references must belong to the
  per-request allowed set (reference grounding).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from .claim_provenance_reader import ClaimProvenanceReader
from .investigation_errors import ClaimProvenanceNotFound, PublicationReadError
from .investigation_evidence import (
    CLUSTER_KEY_PREFIX,
    FILE_KEY_PREFIX,
    MAX_CLUSTER_EVENTS_FOR_LLM,
    MAX_CONTENT_CHARS,
    MAX_RELATED_EVIDENCE,
    EvidenceResolver,
    ResolvedEvidence,
    canonicalize_analysis_input,
    compute_analysis_input_hash,
    expand_timeline_group_rows,
    make_cluster_key,
    make_file_evidence_key,
    normalize_forensic_path,
    parse_cluster_key,
    parse_file_evidence_key,
    read_timeline_group_members,
    validate_timeline_group_descriptor,
)
from .investigation_persistence import (
    ANALYSIS_ACCEPTED,
    ANALYSIS_INVALID,
    ANALYSIS_REVIEW_PENDING,
    BOOTSTRAP_VERSION,
    EVENT_VERSION_INVALID,
    EVENT_VERSION_REVIEW_PENDING,
    GROUNDING_INVALID,
    GROUNDING_PARTIAL,
    GROUNDING_VALID,
    InvestigationPersistence,
    get_investigation_db_path,
)
from .report_dataset import ReportDatasetBuilder
from .citation_validation import CitationGraphBuilder
from .section_planning import SectionPlanBuilder
from .report_render_repository import ReportRenderRepository
from .report_rendering import (
    ConstrainedSectionRenderer,
    SectionRenderBlocked,
    build_section_render_input,
)
from .report_final_validation import (
    FinalSectionValidator,
    ReportRenderCandidateNotFound,
)
from .report_validation_repository import ReportValidationRepository
from .final_report_assembly import (
    FinalReportAssembler,
    FinalReportAssemblyRequest,
    FinalReportAssemblyResult,
    FinalReportPublicationBlocked,
    FINAL_REPORT_VALID,
)
from .final_report_repository import FinalReportRepository
from .final_report_presentation import (
    FinalReportPresentation,
    build_final_report_presentation,
)

logger = logging.getLogger(__name__)

# Canonical evidence keys and bounded-context constants are imported from
# investigation_evidence and re-exported here for Phase 1 API compatibility.

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".svg", ".ico", ".heic", ".heif",
}


# ============================================================================
# Structured secondary-analysis output (LLM contract)
# ============================================================================

class InvestigationClaimIn(BaseModel):
    text: str = Field(..., min_length=1)
    type: str = Field(default="inference")
    evidence_refs: List[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "inference").strip().lower()
        if v not in ("fact", "inference", "hypothesis"):
            return "inference"
        return v


class InvestigationEntityIn(BaseModel):
    local_id: str = Field(..., min_length=1)
    type: str = Field(default="UNKNOWN")
    value: str = Field(..., min_length=1)


class InvestigationRelationIn(BaseModel):
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    type: str = Field(default="related_to")
    kind: str = Field(default="inferred")

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        v = (v or "inferred").strip().lower()
        return v if v in ("observed", "inferred") else "inferred"


class InvestigationAnalysisOut(BaseModel):
    summary: str = ""
    description: str = ""
    claims: List[InvestigationClaimIn] = Field(default_factory=list)
    entities: List[InvestigationEntityIn] = Field(default_factory=list)
    relations: List[InvestigationRelationIn] = Field(default_factory=list)


class InvestigationEventRefreshOut(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str = ""
    evidence_refs: List[str] = Field(default_factory=list)


class InvestigationEventClaimIn(InvestigationClaimIn):
    relation: str = Field(default="supports")

    @field_validator("relation")
    @classmethod
    def _valid_relation(cls, v: str) -> str:
        v = (v or "supports").strip().lower()
        if v not in ("supports", "contradicts"):
            raise ValueError("relation must be supports or contradicts")
        return v


class InvestigationEventRefreshV3Out(InvestigationEventRefreshOut):
    claims: List[InvestigationEventClaimIn] = Field(default_factory=list)


def extract_json_payload(text: str) -> str:
    """Best-effort extraction of a JSON object from an LLM response."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start: end + 1]
    raise ValueError("no JSON object found in LLM response")


# ============================================================================
# Service
# ============================================================================

class InvestigationService:
    """Business logic for the investigation workbench."""

    def __init__(
        self,
        cpp_backend: Any = None,
        llm_service: Any = None,
        graphiti_service: Any = None,
    ):
        self._cpp_backend = cpp_backend
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service
        # fast polling state; SQLite remains the source of truth
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._persistence_cache: Dict[str, InvestigationPersistence] = {}
        self._recoveries: set[str] = set()
        self._evidence_resolver = EvidenceResolver(
            self._get_task_info, content_reader=self._extract_file_text
        )
        self._report_dataset_builder = ReportDatasetBuilder(
            self._get_task_info, self._evidence_resolver
        )
        self._section_renderer = ConstrainedSectionRenderer(llm_service)
        self._render_repository_cache: Dict[str, ReportRenderRepository] = {}
        self._final_validator = FinalSectionValidator()
        self._validation_repository_cache: Dict[str, ReportValidationRepository] = {}
        self._final_report_assembler = FinalReportAssembler()
        self._final_report_repository_cache: Dict[str, FinalReportRepository] = {}

    # ------------------------------------------------------------------
    # task / persistence resolution
    # ------------------------------------------------------------------
    async def _get_task_info(self, task_id: str) -> Dict[str, Any]:
        if self._cpp_backend is None:
            raise RuntimeError("C++ backend not available")
        task_info = await self._cpp_backend.get_task(task_id)
        if not task_info:
            raise KeyError(f"Task {task_id} not found")
        return task_info

    def _task_db_paths(self, task_info: Dict[str, Any]) -> Dict[str, str]:
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

    async def _persistence(self, task_id: str) -> InvestigationPersistence:
        if task_id in self._persistence_cache:
            return self._persistence_cache[task_id]
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        db_path = get_investigation_db_path(paths["files_db"])
        persistence = InvestigationPersistence(db_path)
        if task_id not in self._recoveries:
            persistence.recover_interrupted_jobs()
            persistence.recover_interrupted_event_versions()
            self._recoveries.add(task_id)
        self._persistence_cache[task_id] = persistence
        return persistence

    async def _paths(self, task_id: str) -> Dict[str, str]:
        task_info = await self._get_task_info(task_id)
        return self._task_db_paths(task_info)

    # ------------------------------------------------------------------
    # file evidence adapter (read-only on files.db)
    # ------------------------------------------------------------------
    def _load_file_row(
        self, files_db: str, normalized_path: str
    ) -> Optional[Dict[str, Any]]:
        if not files_db or not os.path.exists(files_db):
            return None
        with sqlite3.connect(files_db, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            # exact match first, then normalized-path match
            row = conn.execute(
                "SELECT * FROM files WHERE path = ? LIMIT 1", (normalized_path,)
            ).fetchone()
            if row is None:
                like = normalized_path.replace("%", "").replace("_", "")
                row = conn.execute(
                    "SELECT * FROM files WHERE REPLACE(path, '\\', '/') = ? LIMIT 1",
                    (normalized_path,),
                ).fetchone() or conn.execute(
                    "SELECT * FROM files WHERE path LIKE ? LIMIT 1",
                    (f"%{like}",),
                ).fetchone()
            return dict(row) if row else None

    async def resolve_evidence(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve a File or Cluster Evidence key inside its owning task."""
        resolved = await self._evidence_resolver.resolve(task_id, evidence_key)
        if resolved is None:
            return None
        result = resolved.to_dict()
        # Preserve Phase 1 field naming for existing clients.
        result["size"] = resolved.source_size
        result["llm_analyzed_at"] = resolved.source_updated_at
        return result

    async def expand_timeline_group(
        self, task_id: str, descriptor: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Expand a trusted Timeline descriptor without trusting client rows."""
        canonical = validate_timeline_group_descriptor(descriptor)
        paths = await self._paths(task_id)
        members = read_timeline_group_members(paths["events_db"], canonical)
        evidence_keys = expand_timeline_group_rows(canonical, members)
        return {
            "descriptor": canonical,
            "member_ids": [int(row["id"]) for row in members],
            "members": members,
            "evidence_keys": evidence_keys,
        }

    async def capture_snapshot(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        """Snapshot the current source state if none exists yet."""
        persistence = await self._persistence(task_id)
        existing = persistence.get_snapshot(task_id, evidence_key)
        if existing:
            return existing
        resolved = await self.resolve_evidence(task_id, evidence_key)
        if resolved is None:
            return None
        persistence.capture_snapshot_if_absent(
            task_id=task_id,
            evidence_key=evidence_key,
            evidence_type=resolved["evidence_type"],
            metadata=resolved.get("metadata"),
            initial_description=resolved.get("initial_description"),
            initial_summary=resolved.get("initial_summary"),
            source_hash=resolved.get("source_hash") or resolved.get("md5"),
            source_size=resolved.get("source_size") or resolved.get("size"),
            source_mtime=resolved.get("source_mtime") or resolved.get("timestamp"),
            source_updated_at=resolved.get("source_updated_at") or resolved.get("llm_analyzed_at"),
        )
        return persistence.get_snapshot(task_id, evidence_key)

    # ------------------------------------------------------------------
    # overview / bootstrap
    # ------------------------------------------------------------------
    async def overview(self, task_id: str) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        return persistence.overview(task_id)

    def _load_analyzed_clusters(
        self, events_db: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Load event clusters that have initial LLM analysis (read-only)."""
        if not events_db or not os.path.exists(events_db):
            return []
        with sqlite3.connect(events_db, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    (timestamp / 60) AS time_window,
                    event_type,
                    MIN(timestamp) AS cluster_start,
                    MAX(timestamp) AS cluster_end,
                    COUNT(*) AS event_count,
                    MAX(llm_summary) AS llm_summary,
                    MAX(llm_description) AS llm_description
                FROM events
                WHERE llm_analyzed_at IS NOT NULL
                GROUP BY time_window, event_type
                ORDER BY cluster_start ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _cluster_related_file_keys(
        self, files_db: str, raw_db: str, cluster_timestamp: int, limit: int = 50
    ) -> List[Tuple[str, str]]:
        """Read-only equivalent of the associations cluster→files matching.

        Returns [(evidence_key, file_path), ...] for files with any timestamp
        within ±300s of the cluster time.
        """
        keys: List[Tuple[str, str]] = []
        if not files_db or not os.path.exists(files_db):
            return keys
        with sqlite3.connect(files_db, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT path, mtime, ctime FROM files ORDER BY mtime DESC LIMIT ?",
                (limit * 3,),
            ).fetchall()
        for row in rows:
            path = row["path"]
            if not path:
                continue
            diffs = [
                abs(ts - cluster_timestamp)
                for ts in (row["mtime"], row["ctime"])
                if ts is not None
            ]
            if diffs and min(diffs) < 300:
                keys.append((make_file_evidence_key(path), path))
            if len(keys) >= limit:
                break
        return keys

    async def bootstrap(self, task_id: str) -> Dict[str, Any]:
        """Create seed investigation events from analyzed clusters (idempotent)."""
        persistence = await self._persistence(task_id)
        paths = await self._paths(task_id)
        clusters = self._load_analyzed_clusters(paths["events_db"])

        created = 0
        for cluster in clusters:
            cluster_key = make_cluster_key(cluster["time_window"], cluster["event_type"])
            title = (
                cluster.get("llm_summary")
                or f"{cluster['event_type']} 活动聚类（{cluster['event_count']} 个事件）"
            )
            summary = cluster.get("llm_description") or ""
            event_id, was_created = persistence.upsert_seed_event(
                task_id=task_id,
                source_cluster_key=cluster_key,
                title=title[:200],
                summary=summary,
                start_time=cluster.get("cluster_start"),
                end_time=cluster.get("cluster_end"),
                category=cluster.get("event_type"),
            )
            if was_created:
                created += 1
            # The cluster itself is primary evidence; correlated files remain supporting.
            persistence.link_evidence(
                task_id, event_id, cluster_key, "event_cluster",
                role="primary", source="cluster_seed", relation_type="source_cluster",
            )
            await self.capture_snapshot(task_id, cluster_key)
            resolved_cluster = await self.resolve_evidence(task_id, cluster_key)
            for evidence_key in (resolved_cluster or {}).get("related_evidence_keys", []):
                persistence.link_evidence(
                    task_id, event_id, evidence_key, "file",
                    role="supporting", source="cluster_seed",
                    relation_type="cluster_member_path",
                )
                await self.capture_snapshot(task_id, evidence_key)

        # Update evidence time bounds from linked file timestamps
        events = persistence.list_events(task_id, limit=1000)
        for event in events:
            links = persistence.list_event_evidence(event["id"], limit=500)
            timestamps: List[int] = []
            for link in links:
                resolved = await self.resolve_evidence(task_id, link["evidence_key"])
                if resolved:
                    await self.capture_snapshot(task_id, link["evidence_key"])
                    if resolved.get("timestamp"):
                        timestamps.append(resolved["timestamp"])
            if timestamps:
                persistence.update_event_times_from_evidence(
                    task_id, event["id"], min(timestamps), max(timestamps)
                )

        persistence.set_meta("bootstrap_version", str(BOOTSTRAP_VERSION))
        overview = persistence.overview(task_id)
        overview["seeded_clusters"] = len(clusters)
        overview["new_events"] = created
        return overview

    # ------------------------------------------------------------------
    # events & evidence listing
    # ------------------------------------------------------------------
    async def list_events(self, task_id: str, **filters) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        events = persistence.list_events(task_id, **filters)
        for index, event in enumerate(events):
            events[index] = await self.get_event(task_id, event["id"])
        return events

    async def get_event(self, task_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        event = persistence.get_event(task_id, event_id)
        if event is None:
            return None
        accepted, pending = persistence.effective_event_version(task_id, event_id)
        flag_mismatch = bool(
            accepted and int(event.get("needs_refresh") or 0) != 0
        )
        if flag_mismatch:
            accepted = None
        event["accepted_title"] = accepted.get("title") if accepted else None
        event["accepted_summary"] = accepted.get("summary") if accepted else None
        event["accepted_version"] = accepted.get("version") if accepted else None
        event["accepted_version_id"] = accepted.get("id") if accepted else None
        pending_stale = bool(
            pending and int(pending.get("source_revision") or 0) != int(event.get("semantic_revision") or 0)
        )
        event["pending_semantic_version"] = pending
        event["pending_semantic_stale"] = pending_stale
        event["effective_semantic_valid"] = bool(accepted and not flag_mismatch)
        if not event["effective_semantic_valid"]:
            event["effective_title"] = event["seed_title"] or event["title"]
            event["effective_summary"] = event["seed_summary"] or event.get("summary")
            event["semantic_source"] = "seed"
            event["semantic_status"] = None
            event["semantic_version"] = None
            event["semantic_version_id"] = None
        elif accepted:
            event["effective_title"] = accepted.get("title") or event["title"]
            event["effective_summary"] = accepted.get("summary") or event.get("summary")
            event["semantic_version"] = accepted.get("version")
            event["semantic_version_id"] = accepted.get("id")
            event["semantic_source"] = "accepted"
            event["semantic_status"] = accepted.get("status")
            event["title"] = event["effective_title"]
            event["summary"] = event["effective_summary"]
        else:
            event["effective_title"] = event["seed_title"] or event["title"]
            event["effective_summary"] = event["seed_summary"] or event.get("summary")
            event["semantic_source"] = "seed"
            event["semantic_status"] = None
            event["semantic_version"] = None
            event["semantic_version_id"] = None
        event["evidence_counts"] = persistence.event_evidence_counts(event_id)
        event["analyst_note"] = persistence.get_note(task_id, "investigation_event", event_id)
        return event

    async def list_event_evidence(
        self, task_id: str, event_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        links = persistence.event_evidence_for_task(task_id, event_id, limit=limit, offset=offset)
        results = []
        for link in links:
            resolved = await self.resolve_evidence(task_id, link["evidence_key"])
            snapshot = persistence.get_snapshot(task_id, link["evidence_key"])
            report = persistence.get_report_evidence(task_id, link["evidence_key"])
            effective = persistence.get_effective_analysis(task_id, link["evidence_key"])
            results.append({
                **link,
                "title": (resolved or {}).get("title")
                or os.path.basename(link["evidence_key"]),
                "timestamp": (resolved or {}).get("timestamp"),
                "initial_summary": (snapshot or resolved or {}).get("initial_summary"),
                "resolved": resolved is not None,
                "has_secondary_analysis": effective is not None,
                "analysis_status": (effective or {}).get("status"),
                "report_usage": (report or {}).get("usage"),
            })
        return results

    async def link_evidence(
        self, task_id: str, event_id: str, evidence_key: str, role: str,
        rationale: Optional[str] = None,
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        if persistence.get_event(task_id, event_id) is None:
            raise KeyError(event_id)
        resolved = await self.resolve_evidence(task_id, evidence_key)
        if resolved is None:
            raise ValueError(f"Evidence {evidence_key} cannot be resolved in task {task_id}")
        await self.capture_snapshot(task_id, evidence_key)
        persistence.link_evidence_for_task(
            task_id, event_id, evidence_key, resolved["evidence_type"],
            role=role, source="analyst", rationale=rationale,
        )
        return {"linked": True, "evidence_key": evidence_key}

    async def unlink_evidence(
        self, task_id: str, event_id: str, evidence_key: str
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        removed = persistence.unlink_evidence_for_task(task_id, event_id, evidence_key)
        return {"unlinked": removed}

    async def evidence_detail(
        self, task_id: str, evidence_key: str
    ) -> Optional[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        resolved = await self.resolve_evidence(task_id, evidence_key)
        if resolved is None:
            return None
        snapshot = await self.capture_snapshot(task_id, evidence_key)
        accepted = persistence.get_accepted_analysis(task_id, evidence_key)
        analysis_history = persistence.list_analyses(task_id, evidence_key)
        pending = next(
            (version for version in analysis_history
             if version["status"] == ANALYSIS_REVIEW_PENDING),
            None,
        )
        latest = analysis_history[0] if analysis_history else None
        report = persistence.get_report_evidence(task_id, evidence_key)
        note = persistence.get_note(task_id, "evidence", evidence_key)
        related_events = persistence.events_for_evidence(task_id, evidence_key)
        return {
            **{k: v for k, v in resolved.items() if k != "metadata"},
            "metadata": resolved.get("metadata"),
            "snapshot": snapshot,
            "accepted_analysis": accepted,
            "pending_analysis": pending,
            "latest_analysis": latest,
            "report_evidence": report,
            "analyst_note": note,
            "related_event_ids": related_events,
        }

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------
    async def save_note(
        self, task_id: str, target_type: str, target_key: str,
        content: str, author: Optional[str] = None,
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        if target_type == "investigation_event":
            persistence.upsert_event_note_and_invalidate(task_id, target_key, content, author)
        else:
            persistence.upsert_note(task_id, target_type, target_key, content, author)
        return persistence.get_note(task_id, target_type, target_key)

    async def get_note(
        self, task_id: str, target_type: str, target_key: str
    ) -> Optional[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        return persistence.get_note(task_id, target_type, target_key)

    # ------------------------------------------------------------------
    # secondary analysis
    # ------------------------------------------------------------------
    def _input_hash(self, payload: Dict[str, Any]) -> str:
        return compute_analysis_input_hash(payload)

    @staticmethod
    def _snapshot_hash_payload(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        snapshot = snapshot or {}
        return {
            "evidence_key": snapshot.get("evidence_key"),
            "evidence_type": snapshot.get("evidence_type"),
            "source_metadata_json": snapshot.get("source_metadata_json"),
            "initial_description": snapshot.get("initial_description"),
            "initial_summary": snapshot.get("initial_summary"),
            "source_hash": snapshot.get("source_hash"),
            "source_size": snapshot.get("source_size"),
            "source_mtime": snapshot.get("source_mtime"),
            "source_updated_at": snapshot.get("source_updated_at"),
        }

    @staticmethod
    def _evidence_hash_payload(resolved: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "evidence_key": resolved.get("evidence_key"),
            "evidence_type": resolved.get("evidence_type"),
            "title": resolved.get("title"),
            "timestamp": resolved.get("timestamp"),
            "start_time": resolved.get("start_time"),
            "end_time": resolved.get("end_time"),
            "metadata": resolved.get("metadata") or {},
            "content": resolved.get("content") or "",
        }

    async def start_evidence_analysis(
        self,
        task_id: str,
        evidence_key: str,
        analyst_note: Optional[str] = None,
        event_id: Optional[str] = None,
        include_case_context: bool = True,
        include_related_evidence: bool = True,
    ) -> Dict[str, Any]:
        """Queue an analyst-guided secondary analysis (async job)."""
        from ..prompts import INVESTIGATION_PROMPT_VERSION

        persistence = await self._persistence(task_id)
        resolved = await self.resolve_evidence(task_id, evidence_key)
        if resolved is None:
            raise ValueError(f"Evidence {evidence_key} cannot be resolved in task {task_id}")
        snapshot = await self.capture_snapshot(task_id, evidence_key)

        # Persist the note (current state) and snapshot its content for audit
        note_id = None
        note_snapshot = None
        if analyst_note is not None:
            note_id = persistence.upsert_note(
                task_id, "evidence", evidence_key, analyst_note
            )
            note_snapshot = analyst_note
        else:
            existing_note = persistence.get_note(task_id, "evidence", evidence_key)
            if existing_note:
                note_id = existing_note["id"]
                note_snapshot = existing_note["content"]

        # Build the allowed evidence set (whitelist) for grounding
        allowed_refs = {evidence_key}
        related_summaries: List[Dict[str, Any]] = []
        if include_related_evidence and event_id:
            if persistence.get_event(task_id, event_id) is None:
                raise KeyError(event_id)
            links = persistence.event_evidence_for_task(task_id, event_id, limit=MAX_RELATED_EVIDENCE)
            for link in links:
                key = link["evidence_key"]
                if key == evidence_key:
                    continue
                other = await self.resolve_evidence(task_id, key)
                if other:
                    allowed_refs.add(key)
                    related_summaries.append({
                        "evidence_key": key,
                        "title": other.get("title"),
                        "timestamp": other.get("timestamp"),
                        "initial_summary": other.get("initial_summary"),
                        "evidence_type": other.get("evidence_type"),
                    })

        case_context = ""
        if include_case_context:
            case_context = await self._load_case_description(task_id)

        input_payload = {
            "evidence_snapshot": self._snapshot_hash_payload(snapshot),
            "evidence_context": self._evidence_hash_payload(resolved),
            "analyst_note": note_snapshot or "",
            "case_context": case_context or "",
            "related_evidence": related_summaries,
            "allowed_evidence_ids": sorted(allowed_refs),
            "prompt_version": INVESTIGATION_PROMPT_VERSION,
        }
        input_hash = self._input_hash(input_payload)

        analysis = persistence.create_analysis_version(
            task_id=task_id,
            evidence_key=evidence_key,
            evidence_type=resolved["evidence_type"],
            analyst_note_id=note_id,
            analyst_note_snapshot=note_snapshot,
            model=None,
            prompt_version=INVESTIGATION_PROMPT_VERSION,
            input_hash=input_hash,
            input_evidence_refs=sorted(allowed_refs),
        )

        job_id = analysis["id"]  # job id == analysis id for traceability
        self._jobs[job_id] = {
            "status": "queued",
            "task_id": task_id,
            "evidence_key": evidence_key,
            "analysis_id": analysis["id"],
            "progress": 0,
        }
        asyncio.create_task(
            self._run_analysis_job(
                job_id=job_id,
                task_id=task_id,
                resolved=resolved,
                snapshot=snapshot,
                analyst_note=note_snapshot,
                case_context=case_context,
                related_summaries=related_summaries,
                allowed_refs=allowed_refs,
                analysis_id=analysis["id"],
            )
        )
        return {"job_id": job_id, "analysis_id": analysis["id"], "version": analysis["version"]}

    async def _load_case_description(self, task_id: str) -> str:
        paths = await self._paths(task_id)
        files_db = paths["files_db"]
        if not files_db or not os.path.exists(files_db):
            return ""
        try:
            with sqlite3.connect(files_db, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT case_description FROM case_analysis WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                return (row["case_description"] if row else "") or ""
        except sqlite3.Error:
            return ""

    async def _extract_file_text(self, file_path: str) -> str:
        """Extract readable text via document extractor, fallback raw read."""
        try:
            from .document_extractor import get_document_extractor_locator
            locator = get_document_extractor_locator()
            extractor = locator.get_extractor(file_path)
            if extractor:
                content = await extractor.extract_to_markdown(file_path)
                return content[:MAX_CONTENT_CHARS]
        except Exception as exc:
            logger.warning("[Investigation] extractor failed for %s: %s", file_path, exc)
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read(MAX_CONTENT_CHARS)
        except OSError as exc:
            raise RuntimeError(f"无法读取证据文件内容: {exc}") from exc

    async def _run_analysis_job(
        self,
        job_id: str,
        task_id: str,
        resolved: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
        analyst_note: Optional[str],
        case_context: str,
        related_summaries: List[Dict[str, Any]],
        allowed_refs: set,
        analysis_id: str,
    ) -> None:
        from ..prompts import (
            INVESTIGATION_ANALYSIS_SYSTEM,
            INVESTIGATION_ANALYSIS_USER_TEMPLATE,
        )

        persistence = await self._persistence(task_id)
        job = self._jobs[job_id]
        job.update({"status": "running", "progress": 10})
        persistence.mark_analysis_running(analysis_id)
        try:
            # ---- build prompt ----
            content_path = resolved.get("content_path")
            file_path = resolved.get("file_path") or resolved.get("title") or ""
            content = ""
            if resolved.get("evidence_type") == "event_cluster":
                content = str(resolved.get("content") or "")[:MAX_CONTENT_CHARS]
            elif content_path and os.path.exists(content_path):
                content = await self._extract_file_text(content_path)
            else:
                logger.warning(
                    "[Investigation] extracted evidence content unavailable: %s "
                    "(continuing with metadata and snapshot)",
                    file_path,
                )

            related_text = "\n".join(
                f"- [{item['evidence_key']}] {item.get('title') or ''} "
                f"(time={item.get('timestamp')}): {(item.get('initial_summary') or '')[:200]}"
                for item in related_summaries
            ) or "（无）"

            user_prompt = INVESTIGATION_ANALYSIS_USER_TEMPLATE.format(
                case_context=case_context or "（无案件背景描述）",
                evidence_key=resolved["evidence_key"],
                evidence_type=resolved.get("evidence_type"),
                evidence_source=resolved.get("file_path") or resolved.get("title") or "",
                file_path=resolved.get("file_path") or "",
                file_metadata=json.dumps(
                    {
                        "name": resolved.get("title"),
                        "evidence_type": resolved.get("evidence_type"),
                        "size": resolved.get("size") or resolved.get("source_size"),
                        "md5": resolved.get("md5"),
                        "mtime": resolved.get("timestamp"),
                        "extension": resolved.get("extension"),
                        **(resolved.get("metadata") or {}),
                    },
                    ensure_ascii=False,
                ),
                initial_analysis=(snapshot or {}).get("initial_description")
                or resolved.get("initial_description")
                or "（初次流水线未生成描述）",
                analyst_note=analyst_note or "（分析员未提供补充说明）",
                related_evidence=related_text,
                content=content or "（证据内容不可用，仅依据元数据与初次分析）",
                allowed_evidence_ids=json.dumps(sorted(allowed_refs), ensure_ascii=False),
            )

            job["progress"] = 30
            if self._llm_service is None:
                raise RuntimeError("LLM service not available")
            result = await self._llm_service.analyze(
                content=content, model_type="text", prompt=user_prompt,
                system_prompt=INVESTIGATION_ANALYSIS_SYSTEM,
            )
            raw_text = (result.get("analysis") or {}).get("description", "")
            model_used = result.get("model")
            job["progress"] = 70

            # ---- parse + validate ----
            payload = extract_json_payload(raw_text)
            parsed = InvestigationAnalysisOut.model_validate_json(payload)

            grounding_status, grounding_warnings, claims = self._ground_claims(
                parsed.claims, allowed_refs
            )
            final_status = (
                ANALYSIS_INVALID
                if grounding_status == GROUNDING_INVALID and parsed.claims
                else ANALYSIS_REVIEW_PENDING
            )

            # ---- persist claims / entities / relations atomically ----
            persistence.complete_analysis_bundle(
                analysis_id=analysis_id,
                description=parsed.description,
                summary=parsed.summary,
                grounding_status=grounding_status,
                grounding_warnings=grounding_warnings,
                status=final_status,
                model=model_used,
                claims=claims,
                entities=[entity.model_dump() for entity in parsed.entities],
                relations=[relation.model_dump() for relation in parsed.relations],
            )

            job.update({"status": "completed", "progress": 100})
            logger.info(
                "[Investigation] task=%s evidence=%s analysis=%s secondary analysis done "
                "(grounding=%s)",
                task_id, resolved["evidence_key"], analysis_id, grounding_status,
            )
        except Exception as exc:
            logger.error(
                "[Investigation] task=%s analysis=%s failed: %s",
                task_id, analysis_id, exc, exc_info=True,
            )
            persistence.fail_analysis(analysis_id, str(exc))
            job.update({"status": "failed", "error": str(exc)})

    def _ground_claims(
        self,
        claims: List[InvestigationClaimIn],
        allowed_refs: set,
    ) -> Tuple[str, List[str], List[Dict[str, Any]]]:
        """Reference-grounding validation of LLM claims.

        Returns (overall_status, warnings, processed_claims). Invalid refs are
        never silently dropped: each removal produces a warning and downgrades
        the claim grounding status. Fact claims without any evidence reference
        are downgraded to hypothesis (analyst-note-only assertions).
        """
        warnings: List[str] = []
        processed: List[Dict[str, Any]] = []
        any_kept = False
        any_dropped = False

        for claim in claims:
            kept = [r for r in claim.evidence_refs if r in allowed_refs]
            dropped = [r for r in claim.evidence_refs if r not in allowed_refs]
            for ref in dropped:
                warnings.append(
                    f"claim '{claim.text[:50]}' referenced unknown evidence {ref!r}; reference removed"
                )
            if dropped and kept:
                status = "partially_grounded"
                any_dropped = True
                any_kept = True
            elif dropped and not kept:
                status = "ungrounded"
                any_dropped = True
            else:
                status = "grounded" if kept else "ungrounded"
                any_kept = any_kept or bool(kept)

            claim_type = claim.type
            origin = "evidence_derived" if kept else "analyst_hypothesis"
            if claim_type == "fact" and not kept:
                claim_type = "hypothesis"
                warnings.append(
                    f"claim '{claim.text[:50]}' downgraded fact→hypothesis: no valid evidence reference"
                )
                origin = "analyst_hypothesis"

            processed.append({
                "text": claim.text,
                "type": claim_type,
                "grounding_status": status,
                "origin": origin,
                "kept_refs": kept,
            })

        if not claims:
            return GROUNDING_VALID, warnings, processed
        if any_dropped and any_kept:
            overall = GROUNDING_PARTIAL
        elif any_dropped and not any_kept:
            overall = GROUNDING_INVALID
        else:
            overall = GROUNDING_VALID
        return overall, warnings, processed

    def _ground_event_claims(
        self, claims: List[InvestigationEventClaimIn], allowed_refs: set[str]
    ) -> List[Dict[str, Any]]:
        """Apply the stricter Event Claim grounding and lifecycle policy."""
        processed: List[Dict[str, Any]] = []
        for claim in claims:
            refs = list(dict.fromkeys(claim.evidence_refs))
            kept = [ref for ref in refs if ref in allowed_refs]
            dropped = [ref for ref in refs if ref not in allowed_refs]
            warnings = [
                f"claim '{claim.text[:50]}' referenced unknown evidence {ref!r}; reference removed"
                for ref in dropped
            ]
            claim_type = claim.type
            status = EVENT_VERSION_REVIEW_PENDING
            if dropped:
                status = EVENT_VERSION_INVALID
            if dropped and kept:
                grounding_status = "partially_grounded"
            elif kept:
                grounding_status = "grounded"
            else:
                grounding_status = "ungrounded"
            if claim_type in ("fact", "inference") and not kept:
                warnings.append(
                    f"claim '{claim.text[:50]}' downgraded {claim_type}→hypothesis: no valid evidence reference"
                )
                claim_type = "hypothesis"
            processed.append({
                "text": claim.text,
                "type": claim_type,
                "status": status,
                "grounding_status": grounding_status,
                "grounding_warnings": warnings,
                "origin": "evidence_derived" if kept else "analyst_hypothesis",
                "kept_refs": kept,
                "relation": claim.relation,
            })
        return processed

    def get_job(self, task_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        if job and job.get("task_id") == task_id:
            return job
        if job is not None:
            return None
        # Fall back to persisted state (e.g. after service restart)
        if job_id in self._persistence_cache:
            pass  # cheap path, unlikely
        return None

    async def get_job_async(
        self, task_id: str, job_id: str
    ) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        if job and job.get("task_id") == task_id:
            return job
        persistence = await self._persistence(task_id)
        analysis = persistence.get_analysis_for_task(task_id, job_id)
        if analysis is not None:
            return {
                "status": "completed" if analysis["status"] in ("review_pending", "accepted", "rejected") else analysis["status"],
                "task_id": task_id,
                "evidence_key": analysis["evidence_key"],
                "analysis_id": analysis["id"],
                "progress": 100 if analysis["completed_at"] else 0,
                "error": analysis["error_message"],
            }
        event_version = persistence.get_event_version_by_id(task_id, job_id)
        if event_version is not None:
            return {"status": "completed" if event_version["status"] == "review_pending" else event_version["status"], "task_id": task_id, "event_id": event_version["event_id"], "version_id": job_id, "progress": 100 if event_version["completed_at"] else 0, "error": event_version["error_message"]}

    # ------------------------------------------------------------------
    # analysis review
    # ------------------------------------------------------------------
    async def list_analyses(self, task_id: str, evidence_key: str) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        versions = persistence.list_analyses(task_id, evidence_key)
        for version in versions:
            if version["status"] in ("review_pending", "accepted", "rejected"):
                claims = persistence.list_claims(version["id"])
                for claim in claims:
                    claim["type"] = claim.pop("claim_type")
                version["claims"] = claims
                version["entities"] = persistence.list_entities(version["id"])
                version["relations"] = persistence.list_relations(version["id"])
        return versions

    async def accept_analysis(
        self, task_id: str, analysis_id: str, acknowledge_warnings: bool = False
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        persistence.accept_analysis(task_id, analysis_id, acknowledge_warnings)
        return persistence.get_analysis(analysis_id)

    async def reject_analysis(self, task_id: str, analysis_id: str) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        persistence.reject_analysis(task_id, analysis_id)
        return persistence.get_analysis(analysis_id)

    # ------------------------------------------------------------------
    # versioned semantic event refresh
    # ------------------------------------------------------------------
    async def start_event_refresh(
        self,
        task_id: str,
        event_id: str,
        analyst_note: Optional[str] = None,
        include_related_evidence: bool = True,
        include_review_pending_analyses: bool = False,
    ) -> Dict[str, Any]:
        from ..prompts import INVESTIGATION_EVENT_REFRESH_PROMPT_VERSION

        persistence = await self._persistence(task_id)
        event = persistence.get_event(task_id, event_id)
        if event is None:
            raise KeyError(event_id)
        note_snapshot = analyst_note
        if analyst_note is not None:
            persistence.upsert_event_note_and_invalidate(task_id, event_id, analyst_note)
            event = persistence.get_event(task_id, event_id) or event
        elif existing_note := persistence.get_note(task_id, "investigation_event", event_id):
            note_snapshot = existing_note["content"]

        links = persistence.event_evidence_for_task(task_id, event_id, limit=MAX_RELATED_EVIDENCE)
        evidence_context: List[Dict[str, Any]] = []
        analysis_ids: List[str] = []
        allowed_refs: List[str] = []
        if include_related_evidence:
            selected_links = links
        else:
            selected_links = [link for link in links if link["role"] == "primary"]
        for link in selected_links:
            evidence = await self.resolve_evidence(task_id, link["evidence_key"])
            if evidence is None:
                continue
            accepted = persistence.get_accepted_analysis(task_id, link["evidence_key"])
            candidate = accepted
            if candidate is None and include_review_pending_analyses:
                candidate = persistence.get_effective_analysis(task_id, link["evidence_key"])
            entry = {
                "evidence_key": link["evidence_key"],
                "role": link["role"],
                "title": evidence.get("title"),
                "initial_summary": evidence.get("initial_summary"),
                "analysis_summary": (candidate or {}).get("summary"),
                "analysis_description": (candidate or {}).get("description"),
                "analysis_status": (candidate or {}).get("status"),
            }
            evidence_context.append(entry)
            allowed_refs.append(link["evidence_key"])
            if candidate:
                analysis_ids.append(candidate["id"])
        if not allowed_refs:
            raise ValueError("event has no resolvable evidence for refresh")
        case_context = await self._load_case_description(task_id)
        input_payload = {
            "event_id": event_id,
            "event_seed": {"title": event.get("seed_title"), "summary": event.get("seed_summary")},
            "analyst_note": note_snapshot or "",
            "case_context": case_context or "",
            "evidence": evidence_context,
            "allowed_evidence_ids": sorted(allowed_refs),
            "prompt_version": INVESTIGATION_EVENT_REFRESH_PROMPT_VERSION,
        }
        version = persistence.create_event_version(
            task_id, event_id, note_snapshot, analysis_ids, allowed_refs,
            self._input_hash(input_payload), int(event.get("semantic_revision") or 0),
            include_review_pending_analyses, INVESTIGATION_EVENT_REFRESH_PROMPT_VERSION,
        )
        job_id = version["id"]
        self._jobs[job_id] = {"status": "queued", "job_type": "event_refresh", "task_id": task_id, "event_id": event_id, "version_id": version["id"], "progress": 0}
        asyncio.create_task(self._run_event_refresh_job(job_id, task_id, event, version, note_snapshot, case_context, evidence_context, set(allowed_refs)))
        return {"job_id": job_id, "version_id": version["id"], "version": version["version"]}

    async def _run_event_refresh_job(self, job_id: str, task_id: str, event: Dict[str, Any], version: Dict[str, Any], analyst_note: Optional[str], case_context: str, evidence_context: List[Dict[str, Any]], allowed_refs: set[str]) -> None:
        from ..prompts import INVESTIGATION_EVENT_REFRESH_SYSTEM, INVESTIGATION_EVENT_REFRESH_USER_TEMPLATE

        persistence = await self._persistence(task_id)
        job = self._jobs[job_id]
        persistence.mark_event_version_running(task_id, event["id"], version["id"])
        job.update({"status": "running", "progress": 20})
        try:
            prompt = INVESTIGATION_EVENT_REFRESH_USER_TEMPLATE.format(
                seed_title=event.get("seed_title") or event.get("title") or "",
                seed_summary=event.get("seed_summary") or event.get("summary") or "",
                analyst_note=analyst_note or "（无）",
                case_context=case_context or "（无）",
                evidence=json.dumps(evidence_context, ensure_ascii=False),
                allowed_evidence_ids=json.dumps(sorted(allowed_refs), ensure_ascii=False),
            )
            if self._llm_service is None:
                raise RuntimeError("LLM service not available")
            result = await self._llm_service.analyze(content=json.dumps(evidence_context, ensure_ascii=False), model_type="text", prompt=prompt, system_prompt=INVESTIGATION_EVENT_REFRESH_SYSTEM)
            output = InvestigationEventRefreshV3Out.model_validate_json(
                extract_json_payload((result.get("analysis") or {}).get("description", ""))
            )
            invalid_refs = [ref for ref in output.evidence_refs if ref not in allowed_refs]
            valid_refs = list(dict.fromkeys(ref for ref in output.evidence_refs if ref in allowed_refs))
            warnings = [f"event refresh referenced unknown evidence {ref!r}" for ref in invalid_refs]
            status = EVENT_VERSION_INVALID if invalid_refs or not valid_refs else EVENT_VERSION_REVIEW_PENDING
            grounding = GROUNDING_INVALID if status == EVENT_VERSION_INVALID else GROUNDING_VALID
            claims = self._ground_event_claims(output.claims, allowed_refs)
            persistence.complete_event_version_bundle(
                task_id, event["id"], version["id"], output.title, output.summary,
                valid_refs, grounding, warnings, status, result.get("model"), claims,
            )
            job.update({"status": "completed" if status != EVENT_VERSION_INVALID else "invalid", "progress": 100})
        except Exception as exc:
            logger.error("[Investigation] task=%s event=%s refresh=%s failed: %s", task_id, event["id"], version["id"], exc, exc_info=True)
            persistence.fail_event_version(task_id, event["id"], version["id"], str(exc))
            job.update({"status": "failed", "error": str(exc)})

    async def get_event_claim_provenance(
        self, task_id: str, claim_id: str
    ) -> Dict[str, Any]:
        """Read historical Claim provenance without opening write persistence."""
        try:
            task_info = await self._get_task_info(task_id)
        except KeyError as exc:
            raise ClaimProvenanceNotFound() from exc
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        reader = ClaimProvenanceReader(get_investigation_db_path(paths["files_db"]))
        try:
            claim = reader.get_claim(task_id, claim_id)
        except FileNotFoundError as exc:
            raise ClaimProvenanceNotFound() from exc
        if claim is None:
            raise ClaimProvenanceNotFound()
        return claim

    async def list_event_versions(self, task_id: str, event_id: str) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        if persistence.get_event(task_id, event_id) is None:
            raise KeyError(event_id)
        return persistence.list_event_versions(task_id, event_id)

    async def list_event_claims(
        self, task_id: str, event_id: str, version_id: str
    ) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        if persistence.get_event_version(task_id, event_id, version_id) is None:
            raise KeyError(version_id)
        return persistence.list_event_claims(task_id, event_id, version_id)

    async def effective_event_claims(
        self, task_id: str, event_id: str
    ) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        if persistence.get_event(task_id, event_id) is None:
            raise KeyError(event_id)
        return persistence.effective_event_claims(task_id, event_id)

    async def review_event_claim(
        self, task_id: str, event_id: str, version_id: str, claim_id: str,
        accepted: bool,
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        return persistence.review_event_claim(
            task_id, event_id, version_id, claim_id,
            EVENT_VERSION_ACCEPTED if accepted else EVENT_VERSION_REJECTED,
        )

    async def accept_event_version(self, task_id: str, event_id: str, version_id: str) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        return persistence.accept_event_version(task_id, event_id, version_id)

    async def reject_event_version(self, task_id: str, event_id: str, version_id: str) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        return persistence.reject_event_version(task_id, event_id, version_id)

    # ------------------------------------------------------------------
    # report evidence
    # ------------------------------------------------------------------
    async def set_report_evidence(
        self, task_id: str, evidence_key: str, usage: str,
        role: Optional[str] = None, report_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        resolved = await self.resolve_evidence(task_id, evidence_key)
        if resolved is None:
            raise ValueError(f"Evidence {evidence_key} cannot be resolved in task {task_id}")
        accepted = persistence.get_accepted_analysis(task_id, evidence_key)
        entry_id = persistence.set_report_evidence(
            task_id=task_id,
            evidence_key=evidence_key,
            evidence_type=resolved["evidence_type"],
            usage=usage,
            role=role,
            report_note=report_note,
            analysis_id=(accepted or {}).get("id"),
            added_by="analyst",
            analyst_confirmed=True,
        )
        return persistence.get_report_evidence(task_id, evidence_key)

    async def remove_report_evidence(
        self, task_id: str, evidence_key: str
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)
        removed = persistence.remove_report_evidence(task_id, evidence_key)
        return {"removed": removed}

    async def list_report_evidence(self, task_id: str) -> List[Dict[str, Any]]:
        persistence = await self._persistence(task_id)
        return persistence.list_report_evidence(task_id)

    async def build_report_dataset(self, task_id: str) -> Dict[str, Any]:
        """Build the read-only deterministic Phase 4A report projection."""
        dataset = await self._report_dataset_builder.build(task_id)
        return dataset.to_response_dict()

    async def validate_report_citations(self, task_id: str) -> Dict[str, Any]:
        """Validate the read-only Phase 4B citation graph."""
        dataset = await self._report_dataset_builder.build(task_id)
        graph = CitationGraphBuilder().build(dataset)
        return graph.to_response_dict()

    async def build_report_section_plan(self, task_id: str) -> Dict[str, Any]:
        """Build the read-only deterministic Phase 4C section plan."""
        dataset = await self._report_dataset_builder.build(task_id)
        graph = CitationGraphBuilder().build(dataset)
        plan = SectionPlanBuilder().build(dataset, graph)
        return plan.to_response_dict()

    async def render_report_section(
        self, task_id: str, section_id: str
    ) -> Dict[str, Any]:
        """Render one valid planned section without changing investigation state."""
        dataset = await self._report_dataset_builder.build(task_id)
        graph = CitationGraphBuilder().build(dataset)
        plan = SectionPlanBuilder().build(dataset, graph)
        input_data = build_section_render_input(dataset, graph, plan, section_id)

        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        repository = self._render_repository_cache.get(task_id)
        if repository is None:
            repository = ReportRenderRepository(
                get_investigation_db_path(paths["files_db"])
            )
            self._render_repository_cache[task_id] = repository
        candidate = repository.create_queued(task_id, section_id, input_data)
        repository.mark_running(candidate.candidate_id)
        result = await self._section_renderer.render(input_data)
        candidate = repository.complete(
            candidate.candidate_id,
            status=result["status"],
            output=result.get("output"),
            raw_llm_output=result.get("raw_llm_output"),
            model=result.get("model"),
            validation_errors=result.get("validation_errors", []),
            error_message=result.get("error_message"),
        )
        return candidate.to_response_dict()

    async def validate_report_section(
        self, task_id: str, candidate_id: str
    ) -> Dict[str, Any]:
        """Validate one immutable 4D Candidate in an independent 4E record."""
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        db_path = get_investigation_db_path(paths["files_db"])
        render_repository = ReportRenderRepository.read_only(db_path)
        candidate = render_repository.get_for_task(task_id, candidate_id)
        if candidate is None:
            raise ReportRenderCandidateNotFound("render candidate not found")

        validation_repository = self._validation_repository_cache.get(task_id)
        if validation_repository is None:
            validation_repository = ReportValidationRepository(db_path)
            self._validation_repository_cache[task_id] = validation_repository
        validation = validation_repository.create_queued(task_id, candidate)
        validation_repository.mark_running(validation.validation_id)

        try:
            dataset = await self._report_dataset_builder.build(task_id)
            graph = CitationGraphBuilder().build(dataset)
            plan = SectionPlanBuilder().build(dataset, graph)
            result = self._final_validator.validate(candidate, dataset, graph, plan)
        except Exception as exc:
            result = self._final_validator.failed(candidate, exc)

        validation = validation_repository.complete(
            validation.validation_id,
            result=result,
        )
        return validation.to_response_dict()

    async def assemble_final_report(
        self,
        task_id: str,
        request: FinalReportAssemblyRequest,
    ) -> Dict[str, Any]:
        """Assemble an explicitly pinned, deterministic Final Report."""
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        db_path = get_investigation_db_path(paths["files_db"])

        dataset = await self._report_dataset_builder.build(task_id)
        graph = CitationGraphBuilder().build(dataset)
        plan = SectionPlanBuilder().build(dataset, graph)
        render_repository = ReportRenderRepository.read_only(db_path)
        validation_repository = ReportValidationRepository.read_only(db_path)
        candidates = {
            binding.candidate_id: render_repository.get_for_task(
                task_id, binding.candidate_id
            )
            for binding in request.sections
            if binding.candidate_id
        }
        validations = {
            binding.validation_id: validation_repository.get_for_task(
                task_id, binding.validation_id
            )
            for binding in request.sections
            if binding.validation_id
        }
        result = self._final_report_assembler.assemble(
            request,
            dataset,
            graph,
            plan,
            candidates,
            validations,
        )
        if result.status != FINAL_REPORT_VALID or result.report is None:
            return result.to_response_dict()

        repository = self._final_report_repository_cache.get(task_id)
        if repository is None:
            repository = FinalReportRepository(db_path)
            self._final_report_repository_cache[task_id] = repository
        report = repository.create_assembled(result.report)
        result = FinalReportAssemblyResult(
            status=result.status,
            errors=result.errors,
            warnings=result.warnings,
            report=report,
        )
        return result.to_response_dict()

    async def list_final_reports(self, task_id: str) -> List[Dict[str, Any]]:
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        repository = FinalReportRepository.read_only(
            get_investigation_db_path(paths["files_db"])
        )
        return [report.to_response_dict() for report in repository.list_reports(task_id)]

    async def get_final_report(self, task_id: str, report_id: str) -> Dict[str, Any]:
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        repository = FinalReportRepository.read_only(
            get_investigation_db_path(paths["files_db"])
        )
        report = repository.get_for_task(task_id, report_id)
        if report is None:
            raise KeyError("final report not found")
        if report.final_report_hash != report.compute_hash():
            raise ValueError("final report hash mismatch")
        return report.to_response_dict()

    async def get_final_report_presentation(
        self,
        task_id: str,
        report_id: str,
        representation: str,
    ) -> FinalReportPresentation:
        """Derive one exact report presentation without persistence or reassembly."""
        try:
            task_info = await self._get_task_info(task_id)
        except KeyError as exc:
            raise KeyError("final report not found") from exc
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise KeyError("final report not found")
        db_path = get_investigation_db_path(paths["files_db"])
        if not db_path.exists():
            raise KeyError("final report not found")
        repository = FinalReportRepository.read_only(db_path)
        try:
            report = repository.get_for_task_strict(task_id, report_id)
        except Exception as exc:
            raise RuntimeError("final report presentation could not be read") from exc
        if report is None:
            raise KeyError("final report not found")
        try:
            return build_final_report_presentation(report, representation)
        except KeyError:
            raise
        except Exception as exc:
            raise ValueError("final report presentation integrity check failed") from exc

    async def get_final_report_publication(
        self, task_id: str, report_id: str
    ) -> Optional[Dict[str, Any]]:
        """Read one exact publication fact without initializing task persistence."""
        try:
            task_info = await self._get_task_info(task_id)
        except KeyError as exc:
            raise KeyError("final report not found") from exc
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise KeyError("final report not found")
        db_path = get_investigation_db_path(paths["files_db"])
        if not db_path.exists():
            raise KeyError("final report not found")
        repository = FinalReportRepository.read_only(db_path)
        try:
            report = repository.get_for_task(task_id, report_id)
        except Exception as exc:
            raise PublicationReadError(
                "publication storage could not be read"
            ) from exc
        if report is None:
            raise KeyError("final report not found")
        try:
            publication = repository.get_publication(task_id, report_id)
        except Exception as exc:
            raise PublicationReadError("publication storage could not be read") from exc
        return publication.to_response_dict() if publication else None

    async def publish_final_report(
        self, task_id: str, report_id: str
    ) -> Dict[str, Any]:
        task_info = await self._get_task_info(task_id)
        paths = self._task_db_paths(task_info)
        if not paths["files_db"]:
            raise RuntimeError(f"Task {task_id} has no files database")
        db_path = get_investigation_db_path(paths["files_db"])
        read_repository = FinalReportRepository.read_only(db_path)
        report = read_repository.get_for_task(task_id, report_id)
        if report is None:
            raise KeyError("final report not found")
        if report.status != "assembled" or report.validation_status != FINAL_REPORT_VALID:
            raise ValueError("final report is not publishable")
        if report.final_report_hash != report.compute_hash():
            raise ValueError("final report hash mismatch")

        render_repository = ReportRenderRepository.read_only(db_path)
        validation_repository = ReportValidationRepository.read_only(db_path)
        for section in report.sections:
            if not section.candidate_id or not section.validation_id:
                continue
            candidate = render_repository.get_for_task(task_id, section.candidate_id)
            validation = validation_repository.get_for_task(task_id, section.validation_id)
            if candidate is None or validation is None:
                raise ValueError("final report binding is no longer available")
            if candidate.section_id != section.section_id:
                raise ValueError("final report Candidate section mismatch")
            if validation.section_id != section.section_id:
                raise ValueError("final report Validation section mismatch")
            if candidate.task_id != task_id or validation.task_id != task_id:
                raise ValueError("final report binding task mismatch")
            if candidate.status != "render_pending_validation":
                raise ValueError("final report Candidate is not pending validation")
            if validation.candidate_id != candidate.candidate_id:
                raise ValueError("final report Validation Candidate mismatch")
            if validation.status != FINAL_REPORT_VALID:
                raise ValueError("final report Validation is no longer valid")
            if validation.validation_result_hash != section.validation_result_hash:
                raise ValueError("final report Validation result hash mismatch")
            binding_pairs = (
                ("dataset_hash", candidate.dataset_hash, report.report_dataset_hash),
                ("citation_graph_hash", candidate.citation_graph_hash, report.citation_graph_hash),
                ("section_plan_hash", candidate.section_plan_hash, report.section_plan_hash),
                ("render_input_hash", candidate.render_input_hash, section.render_input_hash),
                ("render_output_hash", candidate.render_output_hash, section.render_output_hash),
                ("validation_dataset_hash", validation.dataset_hash, report.report_dataset_hash),
                ("validation_citation_graph_hash", validation.citation_graph_hash, report.citation_graph_hash),
                ("validation_section_plan_hash", validation.section_plan_hash, report.section_plan_hash),
                ("validation_render_input_hash", validation.render_input_hash, section.render_input_hash),
                ("validation_render_output_hash", validation.render_output_hash, section.render_output_hash),
                ("observed_dataset_hash", validation.observed_dataset_hash, report.report_dataset_hash),
                ("observed_citation_graph_hash", validation.observed_citation_graph_hash, report.citation_graph_hash),
                ("observed_section_plan_hash", validation.observed_section_plan_hash, report.section_plan_hash),
                ("observed_render_input_hash", validation.observed_render_input_hash, section.render_input_hash),
                ("observed_render_output_hash", validation.observed_render_output_hash, section.render_output_hash),
            )
            for name, actual, expected in binding_pairs:
                if actual != expected:
                    raise ValueError(f"final report binding hash mismatch: {name}")
            if candidate.structured_output is None:
                raise ValueError("final report Candidate output is unavailable")
            persisted_paragraphs = [
                paragraph.model_dump(mode="json")
                for paragraph in candidate.structured_output.paragraphs
            ]
            report_paragraphs = [
                paragraph.model_dump(mode="json")
                for paragraph in section.paragraphs
            ]
            if persisted_paragraphs != report_paragraphs:
                raise ValueError("final report section content mismatch")

        repository = self._final_report_repository_cache.get(task_id)
        if repository is None:
            repository = FinalReportRepository(db_path)
            self._final_report_repository_cache[task_id] = repository
        publication = repository.publish(
            task_id,
            report_id,
            final_report_hash=report.final_report_hash,
        )
        return publication.to_response_dict()

    # ------------------------------------------------------------------
    # local knowledge graph (base KG + overlay)
    # ------------------------------------------------------------------
    async def local_graph(
        self,
        task_id: str,
        evidence_key: Optional[str] = None,
        event_id: Optional[str] = None,
        max_nodes: int = 50,
    ) -> Dict[str, Any]:
        persistence = await self._persistence(task_id)

        # Collect the evidence keys in scope
        keys: List[str] = []
        if evidence_key:
            if await self.resolve_evidence(task_id, evidence_key) is None:
                raise KeyError(evidence_key)
            keys.append(evidence_key)
        if event_id:
            if persistence.get_event(task_id, event_id) is None:
                raise KeyError(event_id)
            links = persistence.event_evidence_for_task(task_id, event_id, limit=max_nodes)
            keys.extend(link["evidence_key"] for link in links)
        keys = list(dict.fromkeys(keys))[:max_nodes]

        overlay = persistence.list_effective_overlay(task_id, keys)

        nodes: Dict[str, Dict[str, Any]] = {}
        links_out: List[Dict[str, Any]] = []

        # Overlay nodes/edges
        entity_lookup: Dict[str, Dict[str, Any]] = {}
        for entity in overlay["entities"]:
            entity_lookup[entity["id"]] = entity
            node_id = f"ov-{entity['id']}"
            nodes[node_id] = {
                "id": node_id,
                "label": entity["display_name"] or entity["canonical_value"],
                "type": entity["entity_type"],
                "source_kind": "investigation",
                "status": entity.get("analysis_status"),
            }
        for relation in overlay["relations"]:
            src = entity_lookup.get(relation["source_entity_id"])
            tgt = entity_lookup.get(relation["target_entity_id"])
            if not src or not tgt:
                continue
            links_out.append({
                "source": f"ov-{src['id']}",
                "target": f"ov-{tgt['id']}",
                "relation_type": relation["relation_type"],
                "relation_kind": relation["relation_kind"],
                "source_kind": "investigation",
                "status": relation.get("analysis_status"),
                "rationale": relation.get("rationale"),
            })

        # Base KG neighbours (best-effort, graceful degradation)
        base_available = self._graphiti_service is not None
        base_error: Optional[str] = None
        if base_available:
            try:
                for key in keys[:10]:
                    resolved = await self.resolve_evidence(task_id, key)
                    if not resolved:
                        continue
                    query = resolved.get("title") or key
                    results = await self._graphiti_service.search(
                        query=query, task_id=task_id, limit=5,
                        include_relationships=True,
                    )
                    for item in results or []:
                        node_id = f"kg-{item.get('id') or item.get('uuid') or item.get('name')}"
                        if node_id not in nodes and len(nodes) < max_nodes:
                            nodes[node_id] = {
                                "id": node_id,
                                "label": item.get("name") or (item.get("properties") or {}).get("name") or "entity",
                                "type": item.get("type") or "Entity",
                                "source_kind": "base",
                                "status": "base",
                            }
            except Exception as exc:  # Neo4j down etc.
                base_available = False
                base_error = str(exc)
                logger.warning("[Investigation] base KG unavailable: %s", exc)

        return {
            "nodes": list(nodes.values())[:max_nodes],
            "links": links_out,
            "base_available": base_available,
            "base_error": base_error,
            "overlay_analysis_status": {
                key: (persistence.get_effective_analysis(task_id, key) or {}).get("status")
                for key in keys
            },
        }
