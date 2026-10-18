"""Canonical serialization for plain (non-model) planning payloads.

``investigation.acquisition.canonical_json`` serializes pydantic models;
the report-runtime derivation validators work on raw dicts inside pydantic
``model_validator(mode="before")`` and need the same byte-stability over
plain values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["canonical_dumps", "sha256_hex", "digest_text"]


def canonical_dumps(value: Any) -> str:
    """Deterministic JSON serialization for plain values (S8 discipline).

    Nested pydantic models (e.g. a submodel inside a ``before`` validator
    payload) are normalized through ``model_dump`` first.
    """
    def _normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: _normalize(sub) for key, sub in item.items()}
        if isinstance(item, (list, tuple, set)):
            return [_normalize(sub) for sub in item]
        if hasattr(item, "model_dump"):
            return _normalize(item.model_dump(mode="json"))
        return item

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def digest_text(value: Any) -> str:
    """Stable digest of one free-text field (never the text itself)."""
    if value is None:
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
