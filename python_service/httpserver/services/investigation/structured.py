"""Strict structured LLM response parsing for Secondary Analysis (C5b)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .models import StructuredAnalysisResponse


class StructuredOutputError(ValueError):
    """The model returned malformed or schema-invalid structured output."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredOutputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StructuredOutputError(f"unsupported JSON constant: {value}")


def parse_structured_analysis_response(content: str) -> StructuredAnalysisResponse:
    """Parse one strict JSON object into an untrusted typed response.

    No markdown fences, embedded JSON, repair, canonicalization, resolving, or
    grounding is performed here. Those concerns belong to later boundaries.
    """
    if not isinstance(content, str) or not content:
        raise StructuredOutputError("structured response must be a non-empty string")
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except StructuredOutputError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StructuredOutputError("invalid structured JSON") from exc
    if not isinstance(payload, dict):
        raise StructuredOutputError("structured response must be a JSON object")
    try:
        return StructuredAnalysisResponse.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError("structured response schema is invalid") from exc
