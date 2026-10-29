"""Identity resolution and edge aggregation for the unified graph.

Merging rules (deliberately conservative, mirroring the people-graph policy):

* A node is keyed by a strong identity: normalized phone number, wxid or QQ
  uin. Multiple strong keys of the same person join into one node only when a
  source explicitly records them together (a contact row carrying both a phone
  and a WeChat id, or an owner record). Nothing is merged on name alone.
* Same-name-different-phone pairs become ``candidates`` — visible to the
  analyst, never auto-merged.
* Groups are their own nodes; member edges come from the chatroom roster, so
  silent members are visible.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .models import (
    Edge,
    GraphFilters,
    Person,
    digest,
    normalize_name,
    normalize_phone,
    normalize_uin,
    normalize_wxid,
)

MAX_RECORD_REFS_PER_EDGE = 20
MAX_SAMPLE_CHARS = 120
_WXID_LIKE = re.compile(r"^wxid_[A-Za-z0-9_-]+$")


@dataclass
class IdentityBucket:
    """Key -> person node id."""

    kinds: dict[str, str] = field(default_factory=dict)

    def key(self, kind: str, value: str) -> str:
        return f"{kind}:{value}"


class Matcher:
    """Union-find over strong identity keys."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._datasets: dict[str, set[str]] = defaultdict(set)
        self._variants: dict[str, set[str]] = defaultdict(set)
        self._conflicts: dict[str, set[str]] = defaultdict(set)
        self._name_to_phones: dict[str, set[str]] = defaultdict(set)

    # -- union-find -------------------------------------------------------
    def _find(self, key: str) -> str:
        self._parent.setdefault(key, key)
        while self._parent[key] != key:
            self._parent[key] = self._parent[self._parent[key]]
            key = self._parent[key]
        return key

    def _union(self, left: str, right: str) -> None:
        a, b = self._find(left), self._find(right)
        if a != b:
            self._parent[b] = a
            if len(self._labels.get(b, "")) > len(self._labels.get(a, "")):
                self._labels[a] = self._labels[b]
            self._variants[a] |= self._variants.pop(b, set())
            self._conflicts[a] |= self._conflicts.pop(b, set())

    # -- registration -----------------------------------------------------
    def observe(self, kind: str, value: str, *, label: str = "",
                dataset: str = "", alias: str = "") -> str | None:
        if not value:
            return None
        key = f"{kind}:{value}"
        self._find(key)
        if label:
            self._labels.setdefault(key, label.strip())
            if alias:
                self._variants[key].add(alias.strip())
        if dataset:
            self._datasets[key].add(dataset)
        return key

    def link(self, left: str | None, right: str | None) -> None:
        """Record that two identity keys belong to the same person."""
        if left and right:
            self._union(left, right)

    def conflict(self, key: str | None, label: str) -> None:
        if key and label:
            self._conflicts[self._find(key)].add(label)

    def register_name_phone(self, name: str, phone_key: str | None) -> None:
        normalized = normalize_name(name)
        if normalized and phone_key:
            self._name_to_phones[normalized].add(phone_key)

    # -- projection -------------------------------------------------------
    def person_id(self, key: str | None) -> str | None:
        if not key:
            return None
        return "p_" + digest(self._find(key))[:24]

    def root(self, key: str | None) -> str | None:
        return self._find(key) if key else None

    def keys_of_kind(self, kind: str) -> list[str]:
        prefix = f"{kind}:"
        return [key for key in self._parent if key.startswith(prefix)]

    def label_of(self, key: str | None) -> str:
        root = self.root(key)
        return self._labels.get(root or "", "") if root else ""

    def build_people(self, nodes: dict[str, Person]) -> list[dict[str, str]]:
        """Materialize person nodes and return same-name merge candidates."""
        grouped: dict[str, list[str]] = defaultdict(list)
        for key in list(self._parent):
            grouped[self._find(key)].append(key)

        for root, keys in grouped.items():
            person_id = "p_" + digest(root)[:24]
            node = nodes.get(person_id)
            if node is None:
                node = Person(id=person_id, label="")
                nodes[person_id] = node
            strong: dict[str, list[str]] = defaultdict(list)
            for key in keys:
                kind, _, value = key.partition(":")
                strong[kind].append(value)
                node.datasets.extend(sorted(self._datasets[key]))
                node.display_variants.extend(sorted(self._variants[key]))
            node.identities = {kind: sorted(set(values)) for kind, values in strong.items()}
            node.datasets = sorted(set(node.datasets))
            node.display_variants = sorted(set(v for v in node.display_variants if v))
            node.identity_conflicts = sorted(self._conflicts.get(root, set()))
            if not node.label:
                # Prefer an explicit display label, then a name variant, then
                # the raw identifier. Never invent a name.
                node.label = (self._labels.get(root, "")
                              or (node.display_variants[0] if node.display_variants else "")
                              or (strong.get("phone", [""])[0])
                              or (strong.get("wxid", [""])[0])
                              or (strong.get("uin", [""])[0])
                              or "未知")

        # Same display name on different person nodes is a candidate merge, not
        # evidence of identity. Report it so the analyst can decide.
        by_name: dict[str, list[str]] = defaultdict(list)
        for person_id, node in nodes.items():
            for name in [node.label, *node.display_variants]:
                normalized = normalize_name(name)
                if normalized:
                    by_name[normalized].append(person_id)
        candidates = []
        seen_pairs = set()
        for normalized, person_ids in by_name.items():
            unique = sorted(set(person_ids))
            if len(unique) < 2:
                continue
            for index, left in enumerate(unique):
                for right in unique[index + 1:]:
                    pair = (left, right)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    candidates.append({
                        "left": left, "right": right, "name": normalized,
                        "reason": "same_display_name_different_identities",
                        "auto_merged": False,
                    })
        return candidates


class EdgeAccumulator:
    """Aggregates raw records into edges between resolved person ids."""

    def __init__(self, owner_id: str | None):
        self.owner_id = owner_id
        self._edges: dict[tuple[str, str, str, str], Edge] = {}

    def add(self, *, source: str | None, target: str | None, relation: str,
            dataset: str, direction: str, timestamp: int | None,
            weight: int = 1, duration: int = 0, media: bool = False,
            sample: str = "", record_ref: str = "") -> None:
        if not source or not target or source == target:
            return
        key = (source, target, relation, dataset)
        edge = self._edges.get(key)
        if edge is None:
            edge = Edge(id="e_" + digest([source, target, relation, dataset])[:24],
                        source=source, target=target, relation=relation,  # type: ignore[arg-type]
                        dataset=dataset, direction=direction)  # type: ignore[arg-type]
            self._edges[key] = edge
        edge.weight += weight
        edge.duration_seconds += duration
        if media:
            edge.media_count += 1
        if timestamp:
            if edge.first_time is None or timestamp < edge.first_time:
                edge.first_time = timestamp
            if edge.last_time is None or timestamp > edge.last_time:
                edge.last_time = timestamp
        if direction != edge.direction:
            if edge.direction == "unknown":
                edge.direction = direction  # type: ignore[assignment]
            elif direction != "unknown":
                edge.direction = "mixed"  # type: ignore[assignment]
        if sample and not edge.sample:
            edge.sample = sample[:MAX_SAMPLE_CHARS]
        if record_ref:
            if len(edge.record_refs) < MAX_RECORD_REFS_PER_EDGE:
                edge.record_refs.append(record_ref)
            else:
                edge.truncated_refs += 1

    def edges(self) -> list[Edge]:
        return list(self._edges.values())


__all__ = ["EdgeAccumulator", "Matcher", "MAX_RECORD_REFS_PER_EDGE"]
