"""Structured tool errors (P3).

Stable machine-readable codes; messages never expose DB paths, filesystem
layout, stack traces or secrets — these strings can reach the model.
"""

from enum import Enum
from typing import Any, Optional


class ToolErrorCode(str, Enum):
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    TOOL_AGENT_NOT_ALLOWED = "TOOL_AGENT_NOT_ALLOWED"
    TOOL_SCOPE_DENIED = "TOOL_SCOPE_DENIED"
    TOOL_INPUT_INVALID = "TOOL_INPUT_INVALID"
    TOOL_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
    TOOL_DUPLICATE_CALL = "TOOL_DUPLICATE_CALL"
    TOOL_ADAPTER_FAILED = "TOOL_ADAPTER_FAILED"
    EVIDENCE_REF_INVALID = "EVIDENCE_REF_INVALID"
    EVIDENCE_REF_CROSS_TASK = "EVIDENCE_REF_CROSS_TASK"
    TOOL_RESULT_INVALID = "TOOL_RESULT_INVALID"


class ToolExecutionError(Exception):
    """One structured tool failure; `code` is the stable machine contract."""

    def __init__(
        self,
        code: ToolErrorCode | str,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
    ):
        try:
            self.code = ToolErrorCode(code)
        except ValueError:
            raise ValueError(f"unknown tool error code: {code!r}") from None
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{self.code.value}: {message}")

    def to_payload(self) -> dict[str, Any]:
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


__all__ = ["ToolErrorCode", "ToolExecutionError"]
