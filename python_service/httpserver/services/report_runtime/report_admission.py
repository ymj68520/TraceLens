"""Report runtime admission (P7A §5-§7).

The P7 report runtime is not a second investigation pipeline: a formal
report planning run binds ONE completed Investigation through its
immutable FinalizationRecord.  Nothing may enter outline planning from an
active investigation, and the admission freezes the exact finalization
anchor (record hash, final working-state revision/hash, completion mode)
so later planning can never silently re-read mutable state.

The existing R2 report generation admission is intentionally untouched:
P7A admission is an additional, stricter gate for the planning plane.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex
from .report_template import (
    FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
    TEMPLATE_STARTER_VERSION,
    ReportTemplateRegistry,
)

REPORT_RUNTIME_ADMISSION_VERSION = "report-runtime-admission:v1"


class ReportRuntimeAdmissionV1(BaseModel):
    """One durable admission binding a report run to a completed case.

    ``admission_id`` is a request identifier (each admission is a distinct
    request); ``input_hash`` covers the semantic binding (investigation +
    finalization anchor + template identity) so two admissions of the same
    binding are visibly equivalent even though both rows are kept.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    admission_version: str = REPORT_RUNTIME_ADMISSION_VERSION

    admission_id: str
    task_id: str
    investigation_id: str

    finalization_id: str
    finalization_record_hash: str
    final_working_state_revision: int
    final_working_state_hash: str

    completion_mode: str

    report_template_id: str
    report_template_version: str
    report_template_hash: str

    report_generation_request_id: str
    requested_by: str

    created_at: str
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("admission_version", REPORT_RUNTIME_ADMISSION_VERSION)
        if not data.get("admission_id"):
            data["admission_id"] = "rra_" + uuid.uuid4().hex
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("admission_id", "created_at", "input_hash")
        }
        data["input_hash"] = sha256_hex(payload)
        return data


class ReportRuntimeAdmissionError(RuntimeError):
    """Admission rejected before any planning artifact exists."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReportRuntimeAdmissionService:
    """Admit one report planning run against a completed Investigation.

    ``runtime_provider`` is the ServiceManager-shaped async factory used by
    the P6B executor: ``async (task_id) -> AgentRuntimeRepository`` built
    from trusted server-side task lookup only.  The whole admission runs on
    read-only repository methods; nothing in the investigation store is
    written or mutated (§60).
    """

    def __init__(
        self,
        runtime_provider: Callable[[str], Awaitable[Any]],
        repository: Any,
        template_registry: ReportTemplateRegistry,
    ):
        self._runtime_provider = runtime_provider
        self._repository = repository
        self._template_registry = template_registry

    async def admit(
        self,
        task_id: str,
        investigation_id: str,
        *,
        requested_by: str,
        template_id: str = FORENSIC_INVESTIGATION_REPORT_TEMPLATE_ID,
        template_version: str = TEMPLATE_STARTER_VERSION,
        report_generation_request_id: Optional[str] = None,
    ) -> ReportRuntimeAdmissionV1:
        try:
            runtime = await self._runtime_provider(task_id)
        except Exception as exc:
            raise ReportRuntimeAdmissionError(
                "task_unavailable",
                f"task store is unavailable: {task_id}",
            ) from exc

        investigation = runtime.get_investigation(investigation_id)
        if investigation is None:
            raise ReportRuntimeAdmissionError(
                "investigation_not_found",
                f"investigation not found: {investigation_id}",
            )
        if investigation.status.value != "completed":
            raise ReportRuntimeAdmissionError(
                "investigation_not_completed",
                "report runtime admission requires a completed "
                f"investigation (current: {investigation.status.value})",
            )

        record = runtime.get_finalization(investigation_id)
        if record is None:
            raise ReportRuntimeAdmissionError(
                "finalization_missing",
                "report runtime admission requires the immutable "
                "FinalizationRecord",
            )

        template = self._template_registry.get(template_id, template_version)
        if template is None:
            raise ReportRuntimeAdmissionError(
                "template_unknown",
                f"unknown report template version: "
                f"{template_id}/{template_version}",
            )

        admission = ReportRuntimeAdmissionV1(
            task_id=task_id,
            investigation_id=investigation_id,
            finalization_id=record.finalization_id,
            finalization_record_hash=record.input_hash,
            final_working_state_revision=record.state_revision,
            final_working_state_hash=record.state_hash,
            completion_mode=record.completion_mode,
            report_template_id=template.template_id,
            report_template_version=template.template_version,
            report_template_hash=template.template_hash,
            report_generation_request_id=(
                report_generation_request_id
                or ("rreq_" + uuid.uuid4().hex)
            ),
            requested_by=requested_by,
        )
        self._repository.record_report_runtime_admission(admission)
        return admission


__all__ = [
    "REPORT_RUNTIME_ADMISSION_VERSION",
    "ReportRuntimeAdmissionError",
    "ReportRuntimeAdmissionService",
    "ReportRuntimeAdmissionV1",
]
