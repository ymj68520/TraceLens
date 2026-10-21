"""Cross-Image Report Generation Admission Service (Phase 1).

Orchestrates the admission of case-level report generation requests:
1. Calls CrossImageEvidenceAggregator to gather multi-task evidence into EnvelopeV4.
2. Canonicalizes envelope to JSON and generates deterministic SHA-256 input_hash.
3. Records admission in reports.db with scope_type='case', scope_id=case_id.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from ..investigation.acquisition import canonical_json
from .cross_image_aggregator import (
    CrossImageEvidenceAggregator,
    CROSS_CASE_REPORT_PROMPT_VERSION,
)
from .models import ReportGenerationInput, ScopeType
from .repository import ReportRepository

logger = logging.getLogger(__name__)


class CrossImageReportAdmissionService:
    """Admission service for cross-image case-level report generation."""

    def __init__(
        self,
        cpp_backend: Any,
        repository: ReportRepository,
        aggregator: Optional[CrossImageEvidenceAggregator] = None,
    ):
        self._cpp_backend = cpp_backend
        self._repository = repository
        self._aggregator = aggregator or CrossImageEvidenceAggregator(cpp_backend)

    async def admit_case(
        self,
        case_id: str,
        *,
        requested_by: str,
        prompt_version: str = CROSS_CASE_REPORT_PROMPT_VERSION,
        override_description: Optional[str] = None,
    ) -> ReportGenerationInput:
        """Admit a cross-image report generation job for a case."""
        envelope = await self._aggregator.assemble_case_envelope(
            case_id,
            prompt_version=prompt_version,
            override_description=override_description,
        )

        canonical = canonical_json(envelope)
        input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        primary_task_id = (
            envelope.devices[0].task_id if envelope.devices else case_id
        )

        import asyncio

        return await asyncio.to_thread(
            self._repository.create_generation_input,
            primary_task_id,
            scope_type=ScopeType.CASE,
            scope_id=case_id,
            requested_by=requested_by,
            input_schema_version=envelope.schema_version,
            prompt_version=prompt_version,
            input_envelope_json=canonical,
            input_hash=input_hash,
        )


__all__ = ["CrossImageReportAdmissionService"]
