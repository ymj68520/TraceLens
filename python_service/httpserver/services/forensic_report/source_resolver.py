from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .analysis_adapter import AnalysisChaptersAdapter
from .models import AdapterContext, EvidenceSource, ScopeType, SourceFingerprint


class ResolvedScope(BaseModel):
    scope_type: ScopeType
    scope_id: str
    title: str
    case_description: str
    task_ids: list[str]
    evidence: list[EvidenceSource]
    contexts: list[AdapterContext]
    analysis: dict[str, Any]


def fingerprint_file(path: str) -> SourceFingerprint:
    candidate = Path(path)
    try:
        with candidate.open("rb") as handle:
            before = os.fstat(handle.fileno())
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(handle.fileno())
            current = candidate.stat()
    except FileNotFoundError:
        return SourceFingerprint(path=str(candidate), exists=False)

    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise RuntimeError(f"source changed while fingerprinting: {candidate}")
    return SourceFingerprint(
        path=str(candidate),
        exists=True,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


class SourceResolver:
    def __init__(self, cpp_backend: Any, analysis_adapter: Any = None):
        self.cpp_backend = cpp_backend
        self.analysis_adapter = analysis_adapter or AnalysisChaptersAdapter()

    async def resolve_task(self, task_id: str) -> ResolvedScope:
        task = await self.cpp_backend.get_task(task_id)
        if not task:
            raise LookupError(f"task not found: {task_id}")

        database_rows = await self.cpp_backend.get_task_databases(task_id)
        db_paths = self._database_paths(database_rows)
        output_files_db = task.get("output_files_db")
        if output_files_db:
            db_paths.setdefault("files", output_files_db)

        fingerprints, analysis = await asyncio.to_thread(
            self._freeze_sources, db_paths, task_id
        )
        evidence_name = Path(task.get("image_path") or task_id).name
        evidence = EvidenceSource(
            evidence_id=task_id,
            task_id=task_id,
            name=evidence_name,
            image_path=task.get("image_path"),
            db_paths=db_paths,
            source_fingerprints=fingerprints,
        )
        relevant_paths = set(analysis.get("filtered_files", []))
        context = AdapterContext(
            scope_type=ScopeType.TASK,
            scope_id=task_id,
            evidence_id=task_id,
            task_id=task_id,
            evidence_name=evidence_name,
            db_paths=db_paths,
            source_fingerprints=fingerprints,
            relevant_paths=relevant_paths,
        )
        return ResolvedScope(
            scope_type=ScopeType.TASK,
            scope_id=task_id,
            title=f"{evidence_name} 取证报告",
            case_description=task.get("case_description") or "",
            task_ids=[task_id],
            evidence=[evidence],
            contexts=[context],
            analysis=analysis,
        )

    def _freeze_sources(
        self, db_paths: dict[str, str], task_id: str
    ) -> tuple[dict[str, SourceFingerprint], dict[str, Any]]:
        fingerprints = {
            name: fingerprint_file(path) for name, path in db_paths.items()
        }
        analysis = self.analysis_adapter.load_task(db_paths.get("files", ""), task_id)
        return fingerprints, analysis

    @staticmethod
    def _database_paths(database_rows: Any) -> dict[str, str]:
        if not isinstance(database_rows, list):
            return {}
        return {
            str(row.get("type") or row.get("database_type") or "").lower(): path
            for row in database_rows
            if isinstance(row, dict) and isinstance((path := row.get("path")), str) and path
        }
