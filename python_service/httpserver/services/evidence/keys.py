"""parse_evidence_key: pure parsing of evidence_key strings into canonical identity.

Frozen key formats:
  file:<normalized_path>
  cluster:v1:<unix_minute>:<encoded_event_type>   (event_type percent-encoded, UTF-8)

Equivalence invariant (C1a): inputs that normalize to the same identity produce
the same ``canonical_key``. event_type is percent-encoded (C1b) so the identity
grammar never depends on the current event_type character set (it tolerates
``foo:bar``, ``微信事件``, etc. without a v2 migration).

This module performs NO database access and NO persistence.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote_to_bytes

from ...path_utils import normalize_evidence_path
from .exceptions import InvalidEvidenceKeyError
from .models import ParsedEvidenceKey

_FILE_PREFIX = "file:"
_CLUSTER_PREFIX = "cluster:"
_SUPPORTED_CLUSTER_VERSION = "v1"

# A '%' not followed by exactly two hex digits (malformed percent-escape).
_MALFORMED_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _decode_event_type(encoded_event_type: str) -> str:
    """Strictly percent-decode event_type; fail closed on malformed/invalid input.

    ``urllib.parse.unquote`` replaces invalid bytes with U+FFFD, which could let
    distinct malformed keys collapse onto one identity. Evidence keys are
    persistent identities, so we reject malformed escapes and non-UTF-8 byte
    sequences instead of silently "repairing" them.
    """
    if _MALFORMED_PERCENT_RE.search(encoded_event_type):
        raise InvalidEvidenceKeyError(f"malformed percent-encoding in event_type: {encoded_event_type!r}")
    raw = unquote_to_bytes(encoded_event_type)
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidEvidenceKeyError(f"event_type is not valid UTF-8: {encoded_event_type!r}") from exc


def parse_evidence_key(evidence_key: str) -> ParsedEvidenceKey:
    """Parse an evidence_key into a canonical ParsedEvidenceKey.

    Raises:
        ValueError: malformed key (unknown type, missing fields, unsupported
            version, non-integer unix_minute, empty event_type, ...).
    """
    if not isinstance(evidence_key, str) or not evidence_key:
        raise InvalidEvidenceKeyError("evidence_key must be a non-empty string")

    if evidence_key.startswith(_FILE_PREFIX):
        raw_path = evidence_key[len(_FILE_PREFIX):]
        if not raw_path:
            raise InvalidEvidenceKeyError("file evidence key missing path")
        normalized_path = normalize_evidence_path(raw_path)
        if not normalized_path:
            raise InvalidEvidenceKeyError("file evidence key has empty normalized path")
        return ParsedEvidenceKey(
            evidence_type="file",
            canonical_key=f"file:{normalized_path}",
            normalized_path=normalized_path,
        )

    if evidence_key.startswith(_CLUSTER_PREFIX):
        # rest == "v1:<unix_minute>:<encoded_event_type>"
        rest = evidence_key[len(_CLUSTER_PREFIX):]
        parts = rest.split(":", 2)
        if len(parts) != 3:
            raise InvalidEvidenceKeyError(f"malformed cluster evidence key: {evidence_key!r}")
        version, minute_str, encoded_event_type = parts
        if version != _SUPPORTED_CLUSTER_VERSION:
            raise InvalidEvidenceKeyError(f"unsupported cluster evidence key version: {version!r}")
        if not encoded_event_type:
            raise InvalidEvidenceKeyError("cluster evidence key missing event_type")
        try:
            unix_minute = int(minute_str)
        except ValueError as exc:
            raise InvalidEvidenceKeyError(
                f"cluster evidence key has non-integer unix_minute: {minute_str!r}"
            ) from exc
        event_type = _decode_event_type(encoded_event_type)
        canonical_encoded = quote(event_type, safe="")  # idempotent re-encode
        return ParsedEvidenceKey(
            evidence_type="cluster",
            canonical_key=f"cluster:v1:{unix_minute}:{canonical_encoded}",
            version=version,
            unix_minute=unix_minute,
            event_type=event_type,
        )

    raise InvalidEvidenceKeyError(f"unknown evidence key type: {evidence_key!r}")
