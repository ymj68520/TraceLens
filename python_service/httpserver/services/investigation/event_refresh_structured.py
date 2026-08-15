"""Strict structured output parsing for Event Refresh narrative generation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .models import StructuredEventRefreshResponse


class StructuredEventRefreshOutputError(ValueError):
    """The refresh model returned malformed or schema-invalid JSON."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredEventRefreshOutputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StructuredEventRefreshOutputError(f"unsupported JSON constant: {value}")


def parse_event_refresh_response(content: str) -> StructuredEventRefreshResponse:
    if not isinstance(content, str) or not content:
        raise StructuredEventRefreshOutputError("refresh response must be non-empty")
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except StructuredEventRefreshOutputError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StructuredEventRefreshOutputError("invalid refresh JSON") from exc
    if not isinstance(payload, dict):
        raise StructuredEventRefreshOutputError("refresh response must be a JSON object")
    try:
        return StructuredEventRefreshResponse.model_validate(payload)
    except ValidationError as exc:
        raise StructuredEventRefreshOutputError("refresh response schema is invalid") from exc
