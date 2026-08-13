"""Task-scoped Evidence identity resolution (Phase C1/C2).

Public API:
    parse_evidence_key(evidence_key) -> ParsedEvidenceKey
    EvidenceResolver(cpp_backend).resolve_evidence(task_id, evidence_key) -> ResolvedEvidence

This package establishes the Investigation trust boundary: callers supply only
(task_id, evidence_key); the resolver confirms the Evidence exists within that
task's own databases and returns a canonical descriptor. It performs no
persistence and never crosses task boundaries.
"""

from .exceptions import EvidenceNotFoundError, EvidenceResolutionError, EvidenceStoreError
from .keys import parse_evidence_key
from .models import ParsedEvidenceKey, ResolvedEvidence
from .resolver import EvidenceResolver

__all__ = [
    "parse_evidence_key",
    "ParsedEvidenceKey",
    "ResolvedEvidence",
    "EvidenceResolver",
    "EvidenceResolutionError",
    "EvidenceNotFoundError",
    "EvidenceStoreError",
]
