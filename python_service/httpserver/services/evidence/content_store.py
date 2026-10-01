"""Durable task content store (evidence content hydration contract v1).

Derived, immutable content backing for parsed File Evidence. The parse
pipeline (C++) persists identity + metadata (files.db) but never file
bytes; the read path used to depend on leftover ``extracted_files/``
artifacts that may not exist. This module closes that gap with, in
priority order (repository audit §6):

1. verified adoption of an existing extraction artifact (hash-checked
   against the parser-produced ``files.db`` hashes);
2. lazy deterministic reacquisition from the original image via the C++
   materialize primitive (raw-DB membership-gated, fail-closed);
3. an explicit, non-fabricated failure with a reason code.

Boundaries (must hold):
- Evidence identity stays ``(task_id, evidence_key)``; nothing here
  introduces content-addressed identity;
- the original image, source rows' forensic metadata and hashes are
  never modified (the image is only ever read by the C++ extractor);
- the store is a derived cache: hash-addressed blobs under the task
  directory plus additive locator columns in the task's own files.db;
- A1-S EvidenceSnapshot stays metadata-only; Initial AI Analysis is
  never a content source; agent reads never mutate Evidence;
- every stored byte is verified against ``files.db.md5``/``size`` at
  write and re-verified (sha256 locator) at read; mismatches fail
  closed instead of serving content.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# §23 reason codes (+ one documented extension). Surfaced verbatim by the
# agent get_evidence tool as content_unavailable_reason.
CONTENT_NOT_PERSISTED_LEGACY = "CONTENT_NOT_PERSISTED_LEGACY"
CONTENT_UNSUPPORTED_TYPE = "CONTENT_UNSUPPORTED_TYPE"
CONTENT_SOURCE_MISSING = "CONTENT_SOURCE_MISSING"
CONTENT_INTEGRITY_MISMATCH = "CONTENT_INTEGRITY_MISMATCH"
CONTENT_READ_FAILED = "CONTENT_READ_FAILED"
CONTENT_EXCEEDS_PERSISTENCE_LIMIT = "CONTENT_EXCEEDS_PERSISTENCE_LIMIT"

BLOB_DIR_PARTS = ("content", "blobs")
# Additive locator columns on the task's own files.db (the canonical parsed
# evidence repository). All C++ writers use explicit column lists, so these
# are invisible to the parser (partition_num additive-migration precedent).
LOCATOR_COLUMNS = (
    ("content_sha256", "TEXT"),
    ("content_size", "INTEGER"),
    ("content_stored_at", "INTEGER"),
)
# Deterministic decode chain (§19): known-product encodings first, strict;
# final fallback replaces undecodable bytes instead of guessing.
DECODE_CHAIN = ("utf-8", "gb18030")
BINARY_SNIFF_BYTES = 8192
DECODE_READ_BYTES = 65536
DEFAULT_PERSISTENCE_LIMIT_BYTES = 64 * 1024 * 1024
_LIMIT_ENV = "EVIDENCE_CONTENT_PERSISTENCE_LIMIT_BYTES"


class ContentUnavailableError(Exception):
    """Content exists as identity but cannot be served; fail-closed."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def persistence_limit_bytes() -> int:
    raw = os.environ.get(_LIMIT_ENV, "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PERSISTENCE_LIMIT_BYTES
    return value if value > 0 else DEFAULT_PERSISTENCE_LIMIT_BYTES


@dataclass(frozen=True)
class LocatedContent:
    """A verified local path for one evidence item's bytes.

    persisted=True: bytes live in the task content store (durable blob,
    locator recorded). persisted=False: bounded reads only (above the
    persistence cap); the path is a reacquired extraction artifact.
    """

    path: str
    sha256: str
    size: int
    persisted: bool
    provenance: str  # "locator" | "adopted" | "reacquired"


def decode_bounded_text(path: str, max_chars: int) -> tuple[str, str]:
    """Deterministic raw-bytes -> bounded text (§19/§20).

    Returns (text, encoding). Raises ContentUnavailableError with
    CONTENT_UNSUPPORTED_TYPE for binary payloads instead of force-decoding.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(BINARY_SNIFF_BYTES)
            if b"\x00" in head:
                raise ContentUnavailableError(
                    CONTENT_UNSUPPORTED_TYPE,
                    "binary payload (NUL byte in leading bytes)",
                )
            raw = head + handle.read(max(0, DECODE_READ_BYTES - len(head)))
    except ContentUnavailableError:
        raise
    except OSError as exc:
        raise ContentUnavailableError(CONTENT_READ_FAILED, str(exc)) from exc
    for encoding in DECODE_CHAIN:
        try:
            return raw.decode(encoding)[:max_chars], encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")[:max_chars], "utf-8+replace"


def _hash_file(path: str) -> tuple[str, str, int]:
    """Return (sha256_hex, md5_hex, size) for the file at path."""
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), md5.hexdigest(), size


class TaskContentStore:
    """Per-task derived content backing, resolved through the C++ backend.

    All paths are derived from the task's own files.db location (never from
    client input) and blob names are hex sha256 digests computed here, so no
    client-controlled string ever becomes a filesystem path component (§15).
    """

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    async def locate_for_resolved(self, resolved) -> LocatedContent:
        """Locate (persisting if needed) the bytes for a resolved file item.

        ``resolved`` is the workbench ResolvedEvidence (or an equivalent
        object exposing task_id, evidence_type, metadata=files-row dict and
        source_files_db). Raises ContentUnavailableError when the content
        cannot be served honestly.
        """
        if getattr(resolved, "evidence_type", "file") not in (None, "file"):
            raise ContentUnavailableError(
                CONTENT_UNSUPPORTED_TYPE,
                f"evidence_type {resolved.evidence_type!r} has no file content",
            )
        files_db = getattr(resolved, "source_files_db", None) or ""
        if not files_db or not os.path.isfile(files_db):
            raise ContentUnavailableError(
                CONTENT_SOURCE_MISSING, f"files.db unavailable: {files_db!r}"
            )
        row = dict(getattr(resolved, "metadata", None) or {})
        stored_path = str(row.get("path") or "")
        if not stored_path:
            raise ContentUnavailableError(
                CONTENT_SOURCE_MISSING, "files row has no path"
            )
        expected_md5 = row.get("md5") or None
        expected_size = row.get("size")
        if not expected_md5:
            raise ContentUnavailableError(
                CONTENT_INTEGRITY_MISMATCH,
                "files row has no parser md5 to verify content against",
            )

        # 1. durable blob via locator
        locator = await self._read_locator(files_db, stored_path)
        if locator:
            sha256, size = locator
            blob = self._blob_path(files_db, sha256)
            if blob.is_file():
                actual = await asyncio.to_thread(self._verify_sha256, str(blob), sha256)
                if not actual:
                    raise ContentUnavailableError(
                        CONTENT_INTEGRITY_MISMATCH,
                        f"stored blob does not match locator sha256 for {stored_path!r}",
                    )
                return LocatedContent(
                    path=str(blob), sha256=sha256, size=size,
                    persisted=True, provenance="locator",
                )
            # stale locator (blob lost) — fall through and re-derive

        # 2/3. candidate on disk (leftover artifact), then image reacquisition
        candidate = await self._extraction_candidate(resolved, stored_path)
        source = candidate
        provenance = "adopted"
        persisted = True
        limit = persistence_limit_bytes()
        oversized = expected_size is not None and int(expected_size) > limit
        if source is None:
            materialized = await self._reacquire(resolved.task_id, stored_path)
            if materialized is None:
                raise ContentUnavailableError(
                    CONTENT_NOT_PERSISTED_LEGACY,
                    f"no extraction artifact and no reacquirable image for {stored_path!r}",
                )
            source = materialized
            provenance = "reacquired"
        if oversized:
            # serve bounded reads from the artifact; do not retain (§21/§55)
            return LocatedContent(
                path=str(source), sha256="", size=int(expected_size),
                persisted=False, provenance=provenance,
            )

        located = await self._persist_verified(
            files_db, stored_path, str(source),
            expected_md5=expected_md5, expected_size=expected_size,
            provenance=provenance,
        )
        if located is None:
            # verification failed on the artifact — never serve it (§13)
            raise ContentUnavailableError(
                CONTENT_INTEGRITY_MISMATCH,
                f"artifact for {stored_path!r} does not match parser md5/size",
            )
        return located

    # ------------------------------------------------------------------
    # candidate discovery + reacquisition
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(path: str) -> str:
        from ..investigation_evidence import normalize_forensic_path

        return normalize_forensic_path(path)

    async def _extraction_candidate(self, resolved, stored_path: str) -> Optional[str]:
        """Existing on-disk artifact for this row (extracted_files leftover).

        Mirrors the workbench resolver's candidate order, but every candidate
        is hash-verified before adoption in _persist_verified.
        """
        import os as _os

        if resolved.content_path and _os.path.isfile(resolved.content_path):
            return resolved.content_path
        return None

    async def _reacquire(self, task_id: str, stored_path: str) -> Optional[str]:
        """Reacquire bytes from the original image via C++ materialize."""
        if self._cpp_backend is None:
            return None
        result = await self._cpp_backend.materialize_file(task_id, stored_path)
        if not isinstance(result, dict) or not result.get("success", True) \
                or not result.get("materialized_path"):
            return None
        path = str(result["materialized_path"])
        return path if os.path.isfile(path) else None

    # ------------------------------------------------------------------
    # persistence (verified first-write; §12/§13/§31)
    # ------------------------------------------------------------------

    async def _persist_verified(
        self,
        files_db: str,
        stored_path: str,
        artifact_path: str,
        *,
        expected_md5: str,
        expected_size,
        provenance: str,
    ) -> Optional[LocatedContent]:
        if not os.path.isfile(files_db):
            # task deleted before we started: never recreate its store (§31)
            raise ContentUnavailableError(
                CONTENT_SOURCE_MISSING, "task deleted before content persistence"
            )
        try:
            sha256, md5, size = await asyncio.to_thread(_hash_file, artifact_path)
        except OSError as exc:
            raise ContentUnavailableError(CONTENT_READ_FAILED, str(exc)) from exc
        if md5 != expected_md5:
            return None
        if expected_size is not None and int(expected_size) != size:
            return None
        blob = self._blob_path(files_db, sha256)
        content_root = blob.parent.parent
        created_top = (
            str(content_root) if not content_root.exists()
            else (str(blob.parent) if not blob.parent.exists() else None)
        )
        if not blob.exists():
            await asyncio.to_thread(self._write_blob_atomic, blob, artifact_path)
        if not os.path.isfile(files_db):
            # task deleted while we worked: never leave a recreated store (§31)
            if created_top:
                await asyncio.to_thread(_remove_tree, created_top)
            raise ContentUnavailableError(
                CONTENT_SOURCE_MISSING, "task deleted during content persistence"
            )
        await self._write_locator(files_db, stored_path, sha256, size)
        return LocatedContent(
            path=str(blob), sha256=sha256, size=size,
            persisted=True, provenance=provenance,
        )

    @staticmethod
    def _blob_path(files_db: str, sha256: str) -> Path:
        # task-owned, hash-addressed: the only path components derived from
        # evidence are hex digests computed here (§15)
        return Path(files_db).parent.joinpath(*BLOB_DIR_PARTS, sha256)

    @staticmethod
    def _write_blob_atomic(blob: Path, artifact_path: str) -> None:
        blob.parent.mkdir(parents=True, exist_ok=True)
        tmp = blob.with_name(blob.name + ".tmp")
        import shutil

        try:
            shutil.copyfile(artifact_path, tmp)
            os.replace(tmp, blob)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _verify_sha256(path: str, expected: str) -> bool:
        try:
            sha = hashlib.sha256()
            with open(path, "rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    sha.update(chunk)
            return sha.hexdigest() == expected
        except OSError:
            return False

    # ------------------------------------------------------------------
    # locator manifest (files.db additive columns)
    # ------------------------------------------------------------------

    @staticmethod
    def _connect(files_db: str, *, ro: bool) -> sqlite3.Connection:
        candidate = Path(files_db)
        if not candidate.is_file():
            raise ContentUnavailableError(
                CONTENT_SOURCE_MISSING, f"files.db unavailable: {files_db!r}"
            )
        if ro:
            uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10)
        else:
            conn = sqlite3.connect(str(candidate), timeout=10)
        return conn

    async def _read_locator(
        self, files_db: str, stored_path: str
    ) -> Optional[tuple[str, int]]:
        def _read() -> Optional[tuple[str, int]]:
            try:
                conn = self._connect(files_db, ro=True)
            except ContentUnavailableError:
                return None
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT content_sha256, content_size FROM files "
                    "WHERE path = ? LIMIT 1",
                    (stored_path,),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT content_sha256, content_size FROM files "
                        "WHERE REPLACE(path, '\\', '/') = ? LIMIT 1",
                        (stored_path,),
                    ).fetchone()
                if row is None or not row["content_sha256"]:
                    return None
                return str(row["content_sha256"]), int(row["content_size"] or 0)
            except sqlite3.Error:
                return None
            finally:
                conn.close()

        return await asyncio.to_thread(_read)

    async def _write_locator(
        self, files_db: str, stored_path: str, sha256: str, size: int
    ) -> None:
        def _write() -> None:
            try:
                conn = self._connect(files_db, ro=False)
            except ContentUnavailableError:
                return
            try:
                self._ensure_locator_columns(conn)
                stored_at = int(time.time())
                conn.execute("PRAGMA busy_timeout = 10000")
                cursor = conn.execute(
                    "UPDATE files SET content_sha256 = ?, content_size = ?, "
                    "content_stored_at = ? WHERE path = ? AND content_sha256 IS NULL",
                    (sha256, size, stored_at, stored_path),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        "UPDATE files SET content_sha256 = ?, content_size = ?, "
                        "content_stored_at = ? WHERE REPLACE(path, '\\', '/') = ? "
                        "AND content_sha256 IS NULL",
                        (sha256, size, stored_at, stored_path),
                    )
                conn.commit()
            except sqlite3.Error as exc:
                # locator is an optimization; blob remains the backing
                logger.warning("content locator write failed for %s: %s", stored_path, exc)
            finally:
                conn.close()

        await asyncio.to_thread(_write)

    @staticmethod
    def _ensure_locator_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(files)").fetchall()
        }
        for name, decl in LOCATOR_COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE files ADD COLUMN {name} {decl}")


def _remove_tree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
