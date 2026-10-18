"""ForensicToolDefinition — TraceLens domain contract for Agent-visible tools (P3).

Named deliberately to avoid colliding with pydantic_ai.tools.ToolDefinition;
the PydanticAI bridge (pydantic_bridge.py) translates between the two.

The full access enum (read/propose/mutate) is part of the contract, but the
P3 ForensicToolRegistry refuses to register any tool whose access is not
``read`` — propose/mutate tools enter only with their real executor phase.
"""

from enum import Enum
from typing import Any, Mapping, Type

from pydantic import BaseModel, ConfigDict, field_validator

from ..agent_runtime import canonical_state_json, state_hash_of


class ToolAccess(str, Enum):
    READ = "read"
    PROPOSE = "propose"
    MUTATE = "mutate"


class ToolCostClass(str, Enum):
    """Non-numeric cost classification (P8 benchmark assigns real costs)."""

    CHEAP = "cheap"
    STANDARD = "standard"
    EXPENSIVE = "expensive"


class ToolPaginationKind(str, Enum):
    NONE = "none"
    PAGE_TOKEN = "page_token"


class ToolScopeKind(str, Enum):
    TASK = "task"
    EVIDENCE = "evidence"
    FILE = "file"
    TIMELINE = "timeline"
    ANALYSIS = "analysis"
    CLAIM = "claim"
    PLATFORM_ARTIFACT = "platform_artifact"


class ToolCategory(str, Enum):
    TASK_CONTEXT = "task_context"
    EVIDENCE = "evidence"
    FILES = "files"
    TIMELINE = "timeline"
    INVESTIGATION_READS = "investigation_reads"
    PLATFORM_ARTIFACTS = "platform_artifacts"


class EvidenceBehavior(str, Enum):
    """How the tool interacts with canonical Evidence identity."""

    # produces evidence_keys that later ground claims
    EVIDENCE_PRODUCING = "evidence_producing"
    # resolves an evidence_key supplied by the caller
    EVIDENCE_RESOLVING = "evidence_resolving"
    NON_EVIDENCE = "non_evidence"


class ForensicToolDefinition(BaseModel):
    """Immutable, hashable description of one forensic tool.

    input_model/output_model are Pydantic models; the registry validates tool
    arguments against input_model and normalized results against output_model.
    """

    model_config = ConfigDict(frozen=True)

    tool_id: str
    version: str
    title: str
    description: str

    input_model: Type[BaseModel]
    output_model: Type[BaseModel]

    category: ToolCategory
    access: ToolAccess
    scope_kind: ToolScopeKind
    evidence_behavior: EvidenceBehavior
    cost_class: ToolCostClass
    pagination_kind: ToolPaginationKind

    # empty tuple = no agent-type restriction (all current agent types may use it)
    allowed_agent_types: tuple[str, ...] = ()

    @field_validator("tool_id")
    @classmethod
    def _check_tool_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or stripped != value or any(c.isspace() for c in stripped):
            raise ValueError("tool_id must be a non-blank identifier without whitespace")
        return stripped

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("version must be non-blank")
        return stripped

    def schema_hash(self) -> str:
        """Deterministic content hash of the tool contract.

        Same catalog -> same hash; any contract change (metadata, input/output
        JSON schema, access/scope rules) changes the hash. Consumed by the
        registry schema_hash, delegation fingerprints and future Context
        input_hash / benchmark manifests.
        """
        payload: dict[str, Any] = {
            "tool_id": self.tool_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "access": self.access.value,
            "scope_kind": self.scope_kind.value,
            "evidence_behavior": self.evidence_behavior.value,
            "cost_class": self.cost_class.value,
            "pagination_kind": self.pagination_kind.value,
            "allowed_agent_types": list(self.allowed_agent_types),
            "input_json_schema": self.input_model.model_json_schema(),
            "output_json_schema": self.output_model.model_json_schema(),
        }
        return state_hash_of(canonical_state_json(payload))

    def input_json_schema(self) -> Mapping[str, Any]:
        """Model-visible input schema (never carries task/run identity fields)."""
        return self.input_model.model_json_schema()

    def output_json_schema(self) -> Mapping[str, Any]:
        return self.output_model.model_json_schema()


def tool_definition_to_payload(definition: ForensicToolDefinition) -> dict[str, Any]:
    """JSON-serializable projection (for manifests / trajectory payloads)."""
    return {
        "tool_id": definition.tool_id,
        "version": definition.version,
        "title": definition.title,
        "category": definition.category.value,
        "access": definition.access.value,
        "scope_kind": definition.scope_kind.value,
        "evidence_behavior": definition.evidence_behavior.value,
        "cost_class": definition.cost_class.value,
        "pagination_kind": definition.pagination_kind.value,
        "schema_hash": definition.schema_hash(),
    }


def validate_model_visible_schema(definition: ForensicToolDefinition) -> None:
    """Audit one input schema for forbidden identity/infrastructure fields.

    Raises ValueError when a model-controllable field collides with trusted
    context identity or execution infrastructure. Used by the registry at
    registration time and by the P3 schema-audit tests.
    """
    forbidden = {
        "task_id",
        "investigation_id",
        "run_id",
        "delegation_id",
        "db_path",
        "database_path",
        "sql",
        "query_sql",
        "table",
        "filesystem_root",
        "service",
    }
    schema = definition.input_json_schema()
    for name in schema.get("properties", {}):
        if name in forbidden:
            raise ValueError(
                f"tool {definition.tool_id!r} input schema exposes forbidden field {name!r}"
            )


__all__ = [
    "EvidenceBehavior",
    "ForensicToolDefinition",
    "ToolAccess",
    "ToolCategory",
    "ToolCostClass",
    "ToolPaginationKind",
    "ToolScopeKind",
    "tool_definition_to_payload",
    "validate_model_visible_schema",
]
