from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "people-graph:v1"
DISCOVERY_PROMPT = "people-discovery:v1"
PRIORITY_PROMPT = "graph-priority:v1"
MAX_FILES = 500
MAX_TEXT = 1_000_000
CHUNK_SIZE = 3200
CHUNK_OVERLAP = 200
MAX_CHUNKS = 300


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def stable_id(prefix, *values):
    return f"{prefix}_{digest(values)[:28]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedPerson(StrictModel):
    local_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["person", "person_reference", "account", "organization"]
    quote: str = Field(min_length=1, max_length=600)
    identity_number: str = Field(default="", max_length=80)
    identity_quote: str = Field(default="", max_length=600)


class ExtractedRelation(StrictModel):
    source: str
    target: str
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["direct", "hypothesis", "co_mentioned", "identity_candidate"]
    quote: str = Field(min_length=1, max_length=800)


class DiscoveryResponse(StrictModel):
    people: list[ExtractedPerson] = Field(default_factory=list, max_length=80)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=100)


class QuoteRef(StrictModel):
    source_id: str
    quote: str = Field(min_length=1, max_length=600)


class IssueRelation(StrictModel):
    question_id: str
    relation: Literal["supports", "inconsistent", "background", "unknown"]


class PrioritySuggestion(StrictModel):
    target_id: str
    relations: list[IssueRelation] = Field(max_length=8)
    key_issue: bool = Field(strict=True)
    core_candidate: bool = Field(default=False, strict=True)
    reason: str = Field(min_length=1, max_length=600)
    refs: list[QuoteRef] = Field(min_length=1, max_length=6)


class PriorityResponse(StrictModel):
    items: list[PrioritySuggestion] = Field(max_length=4)


class StartRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=256)
    mode: Literal["discover", "assess"] = "discover"
    base_run_id: str | None = Field(default=None, pattern=r"^pg_[a-f0-9]{32}$")
    requested_by: str = Field(default="analyst", min_length=1, max_length=256)
    case_description: str | None = Field(default=None, max_length=8000)
    max_files: int = Field(default=200, ge=1, le=MAX_FILES)
    max_graph_relations: int = Field(default=500, ge=1, le=2000)
    max_assessments: int = Field(default=100, ge=1, le=1000)


class IdentityRequest(StrictModel):
    operation: Literal["merge", "split"]
    person_ids: list[str] = Field(min_length=1, max_length=20)
    mention_ids: list[str] = Field(default_factory=list, max_length=500)
    display_name: str = Field(default="", max_length=80)
    reason: str = Field(min_length=1, max_length=1000)
    reviewer: str = Field(default="analyst", min_length=1, max_length=256)


class GraphFilter(StrictModel):
    view: Literal["people", "relations"] = "people"
    priority: Literal["all", "P1", "P1_P2", "P2", "P3", "unassessed", "core"] = "all"
    question_id: str = Field(default="", max_length=32)
    relation_kind: str = Field(default="", max_length=80)
    relation_label: str = Field(default="", max_length=80)
    material_id: str = Field(default="", max_length=80)
    query: str = Field(default="", max_length=120)
    identity_status: Literal["all", "ambiguous", "isolated"] = "all"
    focus_id: str = Field(default="", max_length=100)
    include_context: bool = False
    max_nodes: int = Field(default=200, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
