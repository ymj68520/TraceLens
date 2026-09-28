"""Task-scoped, read-only provenance for a Graphiti relationship.

Graphiti episodes are model input, not original file bytes. This module keeps
those two layers separate and previews only an already-extracted, task-owned
file. It never extracts from an image or modifies evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .evidence import EvidenceNotFoundError
from .evidence.resolver import EvidenceResolver

PREVIEW_BYTES = 16 * 1024
HASH_MAX_BYTES = 8 * 1024 * 1024
_SOURCE_PREFIX = "LLM分析结果 - "
_BINARY_EXTENSIONS = {".pb", ".dat", ".db", ".sqlite", ".exe", ".dll", ".hve", ".bin"}


def _episode_file_path(episode: dict) -> str | None:
    description = episode.get("source_description") or ""
    if description.startswith(_SOURCE_PREFIX):
        return description[len(_SOURCE_PREFIX):].strip() or None
    for line in (episode.get("content") or "").splitlines():
        if line.startswith("file_path: "):
            return line[len("file_path: "):].strip() or None
    return None


def _file_metadata(files_db: str, normalized_path: str) -> dict:
    uri = f"file:{quote(str(Path(files_db).resolve()), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as conn:
        conn.execute("PRAGMA query_only=ON")
        row = conn.execute(
            "SELECT size, md5 FROM files WHERE path=? LIMIT 1", (normalized_path,)
        ).fetchone()
    return {"size": row[0], "md5": row[1] or None} if row else {}


def _preview_extracted(task: dict, normalized_path: str) -> dict:
    files_db = task.get("output_files_db") or ""
    metadata = _file_metadata(files_db, normalized_path) if files_db else {}
    roots = [task.get("extraction_directory")]
    if files_db:
        roots.append(str(Path(files_db).resolve().parent / "extracted_files"))
    for configured in roots:
        if not configured:
            continue
        root = Path(configured).resolve()
        candidate = (root / normalized_path.lstrip("/")).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            continue
        size = candidate.stat().st_size
        with candidate.open("rb") as source:
            prefix = source.read(PREVIEW_BYTES)
        binary = (
            candidate.suffix.lower() in _BINARY_EXTENSIONS
            or b"\x00" in prefix
            or sum(byte < 32 and byte not in (9, 10, 13) for byte in prefix) > len(prefix) // 10
        )
        result = {
            "available": True,
            "kind": "binary" if binary else "text",
            "file_size": size,
            "recorded_size": metadata.get("size"),
            "recorded_md5": metadata.get("md5"),
            "preview_truncated": size > PREVIEW_BYTES,
            "source": "extracted_copy",
            "integrity_note": "提取副本预览；未与原始镜像重新比对",
        }
        if binary:
            result["hex"] = prefix[:512].hex(" ")
            result["printable_strings"] = [
                match.decode("ascii", errors="replace")
                for match in re.findall(rb"[\x20-\x7e]{6,}", prefix)[:30]
            ]
        else:
            result["text"] = prefix.decode("utf-8", errors="replace")
        if size <= HASH_MAX_BYTES:
            sha256 = hashlib.sha256()
            md5 = hashlib.md5() if metadata.get("md5") else None
            with candidate.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    sha256.update(block)
                    if md5:
                        md5.update(block)
            result["copy_sha256"] = sha256.hexdigest()
            result["recorded_md5_matches_copy"] = (
                md5.hexdigest() == metadata["md5"] if md5 else None
            )
        return result
    return {
        "available": False,
        "recorded_size": metadata.get("size"),
        "recorded_md5": metadata.get("md5"),
        "reason": "当前任务未找到该文件的已提取副本",
    }


async def enrich_relationship_trace(trace: dict, task_id: str, manager) -> dict:
    task = await manager.cpp_backend.get_task(task_id)
    if not isinstance(task, dict) or task.get("id") != task_id:
        raise EvidenceNotFoundError("task not found")
    resolver = EvidenceResolver(manager.cpp_backend)
    previews: dict[str, dict] = {}
    enriched = []
    for episode in trace.get("episodes", []):
        item = dict(episode)
        item["source_kind"] = (
            "llm_analysis" if (item.get("source_description") or "").startswith(_SOURCE_PREFIX)
            else "other_episode"
        )
        image_path = _episode_file_path(item)
        item["file_path"] = image_path
        item["evidence_key"] = None
        item["original_preview"] = {"available": False, "reason": "无精确文件来源"}
        if image_path:
            try:
                resolved = await resolver.resolve_evidence(task_id, f"file:{image_path}")
            except (EvidenceNotFoundError, ValueError):
                pass
            else:
                item["file_path"] = resolved.normalized_path
                item["evidence_key"] = resolved.evidence_key
                if resolved.normalized_path not in previews:
                    previews[resolved.normalized_path] = await asyncio.to_thread(
                        _preview_extracted, task, resolved.normalized_path
                    )
                item["original_preview"] = previews[resolved.normalized_path]
        enriched.append(item)
    return {**trace, "episodes": enriched}


async def read_task_source_file(task_id: str, evidence_key: str, manager) -> dict:
    """Resolve one exact task file and its bounded extracted-copy preview."""
    resolved = await EvidenceResolver(manager.cpp_backend).resolve_evidence(
        task_id, evidence_key
    )
    if resolved.evidence_type != "file" or not resolved.normalized_path:
        raise ValueError("source must be a file evidence key")
    task = await manager.cpp_backend.get_task(task_id)
    if not isinstance(task, dict) or task.get("id") != task_id:
        raise EvidenceNotFoundError("task not found")
    preview = await asyncio.to_thread(_preview_extracted, task, resolved.normalized_path)
    snapshot = await manager.investigation_read_service.get_snapshot(
        task_id, resolved.evidence_key
    )
    return {
        "task_id": task_id,
        "evidence_key": resolved.evidence_key,
        "file_path": resolved.normalized_path,
        "original_preview": preview,
        "source_image_available": Path(task.get("image_path") or "").is_file(),
        "snapshot": {
            "captured_at": snapshot.captured_at,
            "initial_description": snapshot.payload.initial_description,
            "initial_summary": snapshot.payload.initial_summary,
        } if snapshot is not None else None,
    }
