"""Atomic snapshot publication for generated reports (Phase R2c).

Follows the A-chain SnapshotWriter publication discipline (staging dir,
immutability re-checked, atomic ``os.replace``, staging cleanup on failure)
but writes ONE canonical JSON artifact: the narrative sections and the
citation manifest are a single ``manifest.json``, so a published report
version can never expose a body without its manifest.

No cross-process claim is needed: every publication uses a fresh uuid4
``report_id`` and failed generations are never retried, so no two
publications can target the same directory.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from .ids import safe_segment
from .models import GenerationReportManifest
from .snapshot_writer import _canonical_json


def new_generation_report_id() -> str:
    """A fresh report version identity (A-chain style plain uuid4)."""
    return str(uuid.uuid4())


class GenerationReportWriter:
    """Publish one generated report snapshot atomically."""

    def __init__(self, report_root: Path):
        self.report_root = Path(report_root)

    def final_dir(
        self,
        task_id: str,
        report_id: str,
        *,
        scope_type: str = "task",
        scope_id: str | None = None,
    ) -> Path:
        resolved_scope = scope_id or task_id
        scope_folder = "case" if scope_type == "case" else "task"
        return (
            self.report_root
            / "snapshots"
            / scope_folder
            / safe_segment(resolved_scope)
            / safe_segment(report_id)
        )

    def publish(
        self,
        *,
        report_id: str,
        manifest: GenerationReportManifest,
        task_id: str | None = None,
        scope_type: str = "task",
        scope_id: str | None = None,
    ) -> Path:
        resolved_scope = scope_id or task_id or manifest.scope_id or manifest.task_id
        final_dir = self.final_dir(
            resolved_scope, report_id, scope_type=scope_type, scope_id=resolved_scope
        )
        if final_dir.exists():
            raise FileExistsError("immutable report already exists")
        staging = self.report_root / ".staging" / safe_segment(report_id)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            staging.mkdir(parents=True)
            (staging / "manifest.json").write_bytes(
                _canonical_json(manifest.model_dump(mode="json"))
            )
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                raise FileExistsError("immutable report already exists")
            os.replace(staging, final_dir)
            return final_dir
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def read_manifest(
        self,
        task_id: str,
        report_id: str,
        *,
        scope_type: str = "task",
        scope_id: str | None = None,
    ) -> dict:
        """Strictly read a published manifest (pure file read, confined).

        The resolved path must stay inside this writer's snapshot root and
        must be a regular file; anything else fails closed.
        """
        resolved_scope = scope_id or task_id
        final_dir = self.final_dir(
            resolved_scope, report_id, scope_type=scope_type, scope_id=resolved_scope
        )
        manifest_path = final_dir / "manifest.json"
        if not manifest_path.is_file() and scope_type == "case":
            legacy_dir = (
                self.report_root
                / "snapshots"
                / safe_segment(scope_type)
                / safe_segment(resolved_scope)
                / safe_segment(report_id)
            )
            if (legacy_dir / "manifest.json").is_file():
                manifest_path = legacy_dir / "manifest.json"
        root = (self.report_root / "snapshots").resolve()
        resolved = manifest_path.resolve()
        if resolved != manifest_path:
            # A symlink component would escape the lexical layout.
            if not str(resolved).startswith(str(root) + os.sep):
                raise FileNotFoundError("report manifest is unavailable")
        if not resolved.is_file():
            raise FileNotFoundError("report manifest is unavailable")
        import json

        return json.loads(resolved.read_bytes().decode("utf-8"))


__all__ = ["GenerationReportWriter", "new_generation_report_id"]
