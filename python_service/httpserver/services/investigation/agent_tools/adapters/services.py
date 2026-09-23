"""Service facade bundle handed to read-only tool adapters (P3)."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ForensicToolServices(BaseModel):
    """Trusted facades (all obtained from ServiceManager in production).

    Kept structural on purpose: adapters rely on documented async methods,
    so tests can inject fakes without subclassing concrete services.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    cpp_backend: Any  # get_task / get_task_files_paginated / get_task_events
    investigation_service: Any  # resolve_evidence / effective_event_claims
    investigation_read_service: Any  # list_evidence
    investigation_event_service: Any  # list_events (optional reads)
    secondary_analysis_executor: Any  # list_analyses / list_all_analyses


def optional_service(bundle: ForensicToolServices, name: str) -> Optional[Any]:
    return getattr(bundle, name, None)


__all__ = ["ForensicToolServices"]
