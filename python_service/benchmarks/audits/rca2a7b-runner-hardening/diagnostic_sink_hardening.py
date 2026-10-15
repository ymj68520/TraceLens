"""RCA-2A.7b hardened diagnostic sink and probe idempotency management.

Guarantees:
- Exclusive sink creation with 0600 permissions.
- Idempotent probe execution: first probe creates and writes; repeated probe
  or interrupted gate recovery performs read-only verification of existing
  artifacts without appending duplicate lines.
- No forgery of idempotency via deletion or mutation.
- Data quality failures fail closed and stop the runner.
- Legitimate model output retries within an invocation emit distinct observations.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from httpserver.services.investigation.agent_failure_diagnostics import (
    JsonlFailureDiagnosticSink,
)


class DiagnosticSinkError(Exception):
    """Base exception for diagnostic sink failures."""


class DiagnosticSinkCollisionError(DiagnosticSinkError):
    """Raised when an exclusive sink already exists and cannot be safely reopened."""


class DiagnosticSinkWriteError(DiagnosticSinkError):
    """Raised when writing to a diagnostic sink fails or produces corrupted data."""


class DiagnosticDataQualityError(DiagnosticSinkError):
    """Raised when diagnostic records fail verification."""


@dataclass(frozen=True)
class ProbeVerificationResult:
    probe_id: str
    sink_path: Path
    mode: str  # "CREATED_AND_RECORDED" or "VERIFIED_EXISTING_READONLY"
    passed: bool
    entries_count: int
    sink_mode_octal: str
    last_entry: dict[str, Any]
    details: dict[str, Any]


def create_exclusive_diagnostic_sink(path: Path) -> JsonlFailureDiagnosticSink:
    """Create a diagnostic sink file exclusively with 0600 permissions.

    Raises DiagnosticSinkCollisionError if the target file already exists.
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DiagnosticSinkCollisionError(
            f"SINK_EXISTS_COLLISION: {path} already exists; exclusive creation refused"
        )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
    except FileExistsError as exc:
        raise DiagnosticSinkCollisionError(
            f"SINK_EXISTS_COLLISION: {path} race condition creation refused"
        ) from exc
    except OSError as exc:
        raise DiagnosticSinkWriteError(
            f"SINK_CREATION_FAILED: unable to create {path}: {exc}"
        ) from exc

    return JsonlFailureDiagnosticSink(path)


def read_and_validate_sink_entries(
    path: Path,
    *,
    expected_stage: str = "SUPERVISOR_INTEGRATE",
    expected_schema_hash: str = "a214ec4f5e81fcbb",
    expected_tool_name: str = "final_result",
    require_validation_details: bool = True,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    """Read and validate existing JSONL failure diagnostic entries.

    Ensures owner-only permissions (0600) and structured field adherence.
    """
    path = path.resolve()
    if not path.is_file():
        raise DiagnosticDataQualityError(f"SINK_FILE_MISSING: {path}")

    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise DiagnosticDataQualityError(
            f"SINK_PERMISSIONS_INSECURE: {path} mode is {oct(mode)}, expected 0o600"
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiagnosticSinkWriteError(f"SINK_READ_FAILED: {path}: {exc}") from exc

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        if allow_empty:
            return []
        raise DiagnosticDataQualityError(f"SINK_EMPTY: {path} contains no entries")

    entries: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DiagnosticDataQualityError(
                f"SINK_CORRUPT_JSON: {path} line {idx+1}: {exc}"
            ) from exc

        # Validate structured fields
        if entry.get("stage") != expected_stage:
            raise DiagnosticDataQualityError(
                f"SINK_STAGE_MISMATCH: {path} line {idx+1} has stage {entry.get('stage')}, expected {expected_stage}"
            )
        if entry.get("schema_hash") != expected_schema_hash:
            raise DiagnosticDataQualityError(
                f"SINK_SCHEMA_HASH_MISMATCH: {path} line {idx+1} schema {entry.get('schema_hash')}, expected {expected_schema_hash}"
            )
        if entry.get("tool_name") != expected_tool_name:
            raise DiagnosticDataQualityError(
                f"SINK_TOOL_NAME_MISMATCH: {path} line {idx+1} tool {entry.get('tool_name')}, expected {expected_tool_name}"
            )
        if require_validation_details and not entry.get("validation_error_details"):
            raise DiagnosticDataQualityError(
                f"SINK_VALIDATION_DETAILS_MISSING: {path} line {idx+1} missing validation_error_details"
            )

        # Verify hard redaction invariants (RCA-1.3): no raw input leak, no api key
        entry_str = json.dumps(entry)
        for forbidden in ("api_key", "authorization", "Bearer ", "password"):
            if forbidden.lower() in entry_str.lower():
                raise DiagnosticDataQualityError(
                    f"SINK_SECURITY_LEAK: {path} contains forbidden credential marker {forbidden!r}"
                )

        entries.append(entry)

    return entries


def execute_or_verify_readiness_probe(
    sink_path: Path,
    probe_id: str,
    probe_fn: Callable[[JsonlFailureDiagnosticSink], Any],
    *,
    expected_stage: str = "SUPERVISOR_INTEGRATE",
    expected_schema_hash: str = "a214ec4f5e81fcbb",
    expected_tool_name: str = "final_result",
) -> ProbeVerificationResult:
    """Execute a deterministic readiness probe idempotently.

    - If sink_path does NOT exist: creates exclusively (0600), runs probe_fn(sink),
      verifies entry written, and returns CREATED_AND_RECORDED.
    - If sink_path ALREADY exists (interrupted gate recovery): does NOT run probe_fn
      and does NOT append. Performs read-only verification of existing entries.
      Returns VERIFIED_EXISTING_READONLY.
    - Prohibits deleting or truncating existing files to fake idempotency.
    """
    sink_path = sink_path.resolve()
    if sink_path.exists():
        # Interrupted gate recovery or repeated probe: read-only verification
        entries = read_and_validate_sink_entries(
            sink_path,
            expected_stage=expected_stage,
            expected_schema_hash=expected_schema_hash,
            expected_tool_name=expected_tool_name,
        )
        mode_octal = oct(sink_path.stat().st_mode & 0o777)
        return ProbeVerificationResult(
            probe_id=probe_id,
            sink_path=sink_path,
            mode="VERIFIED_EXISTING_READONLY",
            passed=True,
            entries_count=len(entries),
            sink_mode_octal=mode_octal,
            last_entry=entries[-1],
            details={
                "idempotent_recovery": True,
                "reused_existing_records": True,
                "appended_new_lines": False,
            },
        )

    # First probe: exclusive create and write
    sink = create_exclusive_diagnostic_sink(sink_path)
    probe_fn(sink)

    # Validate that probe wrote successfully
    entries = read_and_validate_sink_entries(
        sink_path,
        expected_stage=expected_stage,
        expected_schema_hash=expected_schema_hash,
        expected_tool_name=expected_tool_name,
    )
    if len(entries) != 1:
        raise DiagnosticDataQualityError(
            f"PROBE_RECORD_COUNT_UNEXPECTED: expected exactly 1 entry for new probe, got {len(entries)}"
        )

    mode_octal = oct(sink_path.stat().st_mode & 0o777)
    return ProbeVerificationResult(
        probe_id=probe_id,
        sink_path=sink_path,
        mode="CREATED_AND_RECORDED",
        passed=True,
        entries_count=1,
        sink_mode_octal=mode_octal,
        last_entry=entries[0],
        details={
            "idempotent_recovery": False,
            "reused_existing_records": False,
            "appended_new_lines": True,
        },
    )
