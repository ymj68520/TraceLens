"""Strict structured output parsing for report generation (Phase R2c).

Mirrors the C7c-2/C5b strict primitive: ``json.loads`` with duplicate-key
and non-standard-constant rejection, then a frozen ``extra="forbid"``
pydantic model. Markdown fences, embedded JSON, free text, NaN/Infinity,
extra fields, empty required fields, duplicate citation IDs, and sections
referencing unknown citation IDs are all rejected -- no repair, no regex
extraction, no free-text fallback.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .models import StructuredReportResponse


class StructuredReportOutputError(ValueError):
    """The report model returned malformed or schema-invalid JSON."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredReportOutputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StructuredReportOutputError(f"unsupported JSON constant: {value}")


def parse_structured_report_response(content: str) -> StructuredReportResponse:
    if not isinstance(content, str) or not content:
        raise StructuredReportOutputError("report response must be non-empty")
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except StructuredReportOutputError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StructuredReportOutputError("invalid report JSON") from exc
    if not isinstance(payload, dict):
        raise StructuredReportOutputError("report response must be a JSON object")
    try:
        return StructuredReportResponse.model_validate(payload)
    except ValidationError as exc:
        raise StructuredReportOutputError("report response schema is invalid") from exc


__all__ = ["StructuredReportOutputError", "parse_structured_report_response"]
