"""Domain errors for the Investigation Workbench."""


class InvestigationError(Exception):
    """Base error for investigation operations."""


class InvalidEvidenceKey(InvestigationError, ValueError):
    pass


class EvidenceNotFound(InvestigationError, KeyError):
    pass


class EvidenceTaskMismatch(InvestigationError, KeyError):
    pass


class InvalidGrounding(InvestigationError, ValueError):
    pass


class AnalysisNotAcceptable(InvestigationError, ValueError):
    pass


class PublicationReadError(InvestigationError, RuntimeError):
    """Publication storage exists but cannot be read safely."""


class ClaimProvenanceNotFound(InvestigationError, KeyError):
    """Opaque not-found error for task-scoped historical Claim provenance."""


class EventNotFound(InvestigationError, KeyError):
    pass


class EventRefreshInvalid(InvestigationError, ValueError):
    pass


class VersionConflict(InvestigationError, ValueError):
    pass


class UnsupportedSchemaVersion(InvestigationError, RuntimeError):
    pass
