"""Exception hierarchy for Evidence resolution (C2.1).

Distinguishes "the Evidence/task does not exist" (not-found) from "the task's
evidence store is unusable" (DB / schema / query failure). These are internal
for now; C3 will map them to distinct HTTP statuses. Keeping them separate means
an analyst never sees "Evidence not found" when the real cause is a corrupted
task database.
"""

from __future__ import annotations


class InvalidEvidenceKeyError(ValueError):
    """The client supplied a malformed Evidence key (HTTP 400 semantics)."""


class EvidenceResolutionError(Exception):
    """Base class for Evidence resolution failures."""


class EvidenceNotFoundError(EvidenceResolutionError, LookupError):
    """The task or Evidence does not exist (not-found semantics).

    Subclasses LookupError so generic ``except LookupError`` callers continue
    to treat resolution failure as "not found".
    """


class EvidenceStoreError(EvidenceResolutionError):
    """The task's evidence store cannot be read.

    Raised when the database file is missing, a required table is missing, or a
    SQLite query/schema error occurs. This is NOT a not-found condition: it means
    the system could not verify the Evidence at all.
    """
