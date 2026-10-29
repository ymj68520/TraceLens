"""Data models for the unified communication graph."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Identity classes. Only the first three are strong enough to merge nodes.
IdentityKind = Literal["phone", "wxid", "uin", "name"]

STRONG_IDENTITY_KINDS = frozenset({"phone", "wxid", "uin"})

_WHITESPACE = re.compile(r"[\s\-()（）]")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                   separators=(",", ":")).encode()
    ).hexdigest()


def normalize_phone(value: str | None) -> str:
    """Strip separators and a leading +86 / 0086 country code.

    Returns "" when nothing plausible remains. A phone number is the only
    identity key that crosses every source family (contacts, call logs, SMS,
    and — when the backup carries it — WeChat/QQ profile data), so its
    normalization must be conservative: no digit trimming of short codes.
    """
    if not value:
        return ""
    text = _WHITESPACE.sub("", str(value)).strip()
    if not text:
        return ""
    if text.startswith("+86"):
        text = text[3:]
    elif text.startswith("0086"):
        text = text[4:]
    elif text.startswith("86") and len(text) == 13:
        text = text[2:]
    if not text.isdigit():
        return ""
    # Anything shorter than 5 digits is a service short code, not a subscriber.
    if len(text) < 5 or len(text) > 20:
        return ""
    return text


def normalize_wxid(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text or "@chatroom" in text:
        return ""
    return text


def normalize_uin(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    return text if text.isdigit() else ""


def normalize_name(value: str | None) -> str:
    return (str(value).strip() if value else "").casefold()


@dataclass(frozen=True)
class DatasetRef:
    """One readable communication source belonging to a case."""

    kind: Literal["task", "wechat_import", "qq_import"]
    id: str
    path: str
    label: str

    @property
    def dataset_id(self) -> str:
        return f"{self.kind}:{self.id}"


@dataclass
class Dataset:
    """A resolved source plus the tables it actually carries."""

    ref: DatasetRef
    tables: frozenset[str] = frozenset()
    owner: dict[str, str] = field(default_factory=dict)


class GraphFilters(BaseModel):
    """Query filters. Applied before the viewport limit, never after."""

    model_config = ConfigDict(extra="forbid")

    start_time: int | None = Field(default=None, ge=0)
    end_time: int | None = Field(default=None, ge=0)
    datasets: list[str] = Field(default_factory=list)
    min_edge_weight: int = Field(default=1, ge=1, le=1_000_000)
    include_union: bool = Field(
        default=True, description="Merge datasets into one graph; false keeps them apart"
    )
    max_nodes: int = Field(default=500, ge=1, le=2000)
    max_edges: int = Field(default=2000, ge=1, le=10000)
    communities: bool = True

    def accepts(self, dataset_id: str) -> bool:
        return not self.datasets or dataset_id in self.datasets


class Person(BaseModel):
    """A graph node: one person (possibly several identity keys)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: Literal["person", "group", "owner", "unknown"] = "person"
    identities: dict[str, list[str]] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)
    message_count: int = 0
    call_count: int = 0
    sms_count: int = 0
    first_time: int | None = None
    last_time: int | None = None
    is_owner: bool = False
    display_variants: list[str] = Field(default_factory=list)
    identity_conflicts: list[str] = Field(default_factory=list)


class Edge(BaseModel):
    """One relationship between two nodes, aggregated over all its records."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    relation: Literal["call", "sms", "im_private", "im_group", "group_member"]
    dataset: str
    direction: Literal["sent", "received", "unknown", "mixed"] = "unknown"
    weight: int = 0
    duration_seconds: int = 0
    first_time: int | None = None
    last_time: int | None = None
    media_count: int = 0
    sample: str = ""
    record_refs: list[str] = Field(default_factory=list)
    truncated_refs: int = 0


class UnifiedGraph(BaseModel):
    """Graph payload plus the coverage facts a reader needs."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Person] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    communities: list[list[str]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "Dataset",
    "DatasetRef",
    "Edge",
    "GraphFilters",
    "Person",
    "STRONG_IDENTITY_KINDS",
    "UnifiedGraph",
    "digest",
    "normalize_name",
    "normalize_phone",
    "normalize_uin",
    "normalize_wxid",
]
