"""Unified communication graph service.

Reads every resolvable source, resolves identity, aggregates edges and answers
the questions the mobile analysis phase needs:

* who talks to whom (``build_graph``)
* what happened when (``build_timeline``)
* which records back a specific edge (``edge_detail``)

All entry points are read-only and never rebuild the source databases.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .datasets import resolve_datasets
from .identity import EdgeAccumulator, Matcher, MAX_RECORD_REFS_PER_EDGE
from .models import (
    DatasetRef,
    Edge,
    GraphFilters,
    Person,
    UnifiedGraph,
    digest,
    normalize_phone,
    normalize_uin,
    normalize_wxid,
)
from .sources import (
    MAX_ROWS_PER_SOURCE,
    open_dataset,
    read_call_logs,
    read_contacts,
    read_mobile_artifacts,
    read_owner,
    read_sms,
    read_wechat_chatrooms,
    read_wechat_contacts,
    read_wechat_messages,
)

MAX_REF_LIST = MAX_RECORD_REFS_PER_EDGE

# Coverage counters exposed on every payload.
_COVERAGE_KEYS = (
    "datasets_total", "datasets_readable", "datasets_unavailable",
    "messages_read", "calls_read", "sms_read", "contacts_read", "artifacts_read",
    "truncated_sources", "merged_identities", "name_candidates",
    "orphan_records", "owner_unknown_datasets",
)


class CommGraphService:
    """Builds and queries the unified communication graph."""

    def __init__(self, cpp_backend: Any):
        self._cpp = cpp_backend

    async def resolve(self, task_id: str, *, wechat_imports: Iterable[str] = (),
                      qq_imports: Iterable[str] = ()):
        task = await self._cpp.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise LookupError("task not found")
        return resolve_datasets(task, wechat_imports=wechat_imports, qq_imports=qq_imports)

    def build_graph(self, refs: list[DatasetRef], filters: GraphFilters, *,
                    unavailable: list[dict[str, str]] | None = None) -> UnifiedGraph:
        return _build(refs, filters, unavailable or [])


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(str(Path(path).resolve()), safe='/')}?mode=ro",
                           uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _guarded(callable_, *args, **kwargs) -> list[dict[str, Any]]:
    try:
        return list(callable_(*args, **kwargs))
    except sqlite3.DatabaseError:
        return []


def _in_range(edge: Edge, start: int | None, end: int | None) -> bool:
    if start is None and end is None:
        return True
    if edge.first_time is None and edge.last_time is None:
        # Undated records cannot be proven to fall inside a requested range.
        return False
    low = edge.first_time if edge.first_time is not None else edge.last_time
    high = edge.last_time if edge.last_time is not None else edge.first_time
    assert low is not None and high is not None
    if start is not None and high < start:
        return False
    if end is not None and low > end:
        return False
    return True


def _merge_edges(edges: list[Edge]) -> list[Edge]:
    """Union view: same endpoint pair + relation collapse across datasets."""
    merged: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = tuple(sorted((edge.source, edge.target))) + (edge.relation,)
        existing = merged.get(key)
        if existing is None:
            copy = edge.model_copy(deep=True)
            copy.dataset = edge.dataset
            merged[key] = copy
            continue
        existing.weight += edge.weight
        existing.duration_seconds += edge.duration_seconds
        existing.media_count += edge.media_count
        for ref in edge.record_refs:
            if len(existing.record_refs) < MAX_REF_LIST:
                existing.record_refs.append(ref)
            else:
                existing.truncated_refs += 1
        existing.truncated_refs += edge.truncated_refs
        if edge.first_time and (existing.first_time is None or edge.first_time < existing.first_time):
            existing.first_time = edge.first_time
        if edge.last_time and (existing.last_time is None or edge.last_time > existing.last_time):
            existing.last_time = edge.last_time
        if edge.direction != existing.direction:
            if existing.direction == "unknown":
                existing.direction = edge.direction  # type: ignore[assignment]
            elif edge.direction != "unknown":
                existing.direction = "mixed"  # type: ignore[assignment]
        if edge.dataset != existing.dataset:
            existing.dataset = "union"
    return list(merged.values())


def _communities(nodes: list[Person], edges: list[Edge]) -> list[list[str]]:
    try:
        import networkx as nx
    except ImportError:
        return []
    graph = nx.Graph()
    graph.add_nodes_from(node.id for node in nodes)
    for edge in edges:
        graph.add_edge(edge.source, edge.target, weight=edge.weight)
    try:
        import community as community_louvain  # type: ignore[import-not-found]
        partition = community_louvain.best_partition(graph, weight="weight")
        grouped: dict[int, list[str]] = {}
        for node, cluster in partition.items():
            grouped.setdefault(cluster, []).append(node)
        return list(grouped.values())
    except ImportError:
        return [list(component) for component in nx.connected_components(graph)]


def _metrics(nodes: list[Person], edges: list[Edge],
             communities: list[list[str]]) -> dict[str, Any]:
    try:
        import networkx as nx
    except ImportError:
        return {}
    graph = nx.DiGraph()
    graph.add_nodes_from(node.id for node in nodes)
    for edge in edges:
        graph.add_edge(edge.source, edge.target, weight=edge.weight)
    result: dict[str, Any] = {}
    try:
        result["pagerank"] = {key: round(value, 6)
                              for key, value in nx.pagerank(graph, weight="weight").items()}
    except Exception:  # pragma: no cover - networkx version variance
        result["pagerank"] = {}
    try:
        result["betweenness"] = {
            key: round(value, 6)
            for key, value in nx.betweenness_centrality(graph, weight="weight").items()}
    except Exception:  # pragma: no cover
        result["betweenness"] = {}
    result["communities"] = len(communities)
    return result


def _build(refs: list[DatasetRef], filters: GraphFilters,
           unavailable: list[dict[str, str]]) -> UnifiedGraph:
    matcher = Matcher()
    nodes: dict[str, Person] = {}
    coverage = {key: 0 for key in _COVERAGE_KEYS}
    coverage["datasets_total"] = len(refs) + len(unavailable)
    coverage["datasets_unavailable"] = len(unavailable)
    datasets_payload: list[dict[str, Any]] = []
    truncated: list[str] = []
    accumulators: list[EdgeAccumulator] = []
    group_members: dict[tuple[str, str], set[str]] = {}
    group_labels: dict[tuple[str, str], str] = {}

    for ref in refs:
        if not filters.accepts(ref.dataset_id):
            continue
        dataset = open_dataset(ref)
        if dataset is None:
            unavailable.append({"kind": ref.kind, "id": ref.id,
                                "reason": "unreadable_or_missing"})
            coverage["datasets_unavailable"] += 1
            continue
        coverage["datasets_readable"] += 1
        datasets_payload.append({
            "dataset_id": ref.dataset_id,
            "kind": ref.kind,
            "id": ref.id,
            "label": ref.label,
            "tables": sorted(dataset.tables),
        })

        with closing(_connect(ref.path)) as conn:
            owner = read_owner(conn)
            owner_username = normalize_wxid(owner.get("username"))
            owner_uin = normalize_uin(owner.get("uin"))
            owner_key = None
            if owner_username:
                owner_key = matcher.observe("wxid", owner_username,
                                            label=owner.get("nickname") or owner_username,
                                            dataset=ref.dataset_id)
            if owner_uin:
                uin_key = matcher.observe("uin", owner_uin,
                                          label=owner.get("nickname") or owner_uin,
                                          dataset=ref.dataset_id)
                matcher.link(owner_key, uin_key)
                owner_key = owner_key or uin_key
            if owner_key is None:
                # Sources that carry calls/SMS but no IM owner record (MIUI,
                # Meiya, ThunderForensic) still need a hub. This is an explicit
                # "device owner of this dataset", not an invented phone number.
                owner_key = matcher.observe("owner", ref.dataset_id,
                                            label=f"本机（{ref.label}）",
                                            dataset=ref.dataset_id)
                coverage["owner_unknown_datasets"] += 1
            else:
                # Mark the IM owner as the device owner of this dataset too, so
                # ``is_owner`` is set regardless of whether we had to synthesize
                # a hub.
                matcher.link(owner_key, matcher.observe("owner", ref.dataset_id,
                                                        dataset=ref.dataset_id))
            owner_id = matcher.person_id(owner_key)
            assert owner_id is not None

            _load_contacts(conn, ref, matcher, coverage)
            _load_chatrooms(conn, ref, matcher, coverage, group_members, group_labels)
            _load_wechat(conn, ref, matcher, coverage, accumulators, owner_username,
                         owner_id, group_members, truncated)
            _load_calls(conn, ref, matcher, coverage, accumulators, owner_id, truncated)
            _load_sms(conn, ref, matcher, coverage, accumulators, owner_id, truncated)
            _load_artifacts(conn, ref, matcher, coverage, accumulators, owner_id, truncated)

    candidates = matcher.build_people(nodes)
    coverage["merged_identities"] = sum(
        1 for node in nodes.values() if sum(len(v) for v in node.identities.values()) > 1)
    coverage["name_candidates"] = len(candidates)

    for key in matcher.keys_of_kind("owner"):
        person_id = matcher.person_id(key)
        node = nodes.get(person_id) if person_id else None
        if node is not None:
            node.is_owner = True
            node.kind = "owner"

    # Group hubs: keyed by (dataset, group) so identical names in two accounts
    # do not collapse into one node.
    for (dataset_id, group), members in group_members.items():
        group_id = "g_" + digest([dataset_id, group])[:24]
        node = nodes.get(group_id) or Person(id=group_id, label=group, kind="group")
        node.label = group_labels.get((dataset_id, group), group)
        node.datasets = sorted(set(node.datasets) | {dataset_id})
        nodes[group_id] = node
        accumulator = EdgeAccumulator(None)
        for member in sorted(members):
            member_id = matcher.person_id(f"wxid:{member}")
            if not member_id or member_id == group_id:
                continue
            accumulator.add(source=member_id, target=group_id,
                            relation="group_member", dataset=dataset_id,
                            direction="unknown", timestamp=None, weight=1,
                            record_ref=f"{dataset_id}|chatroom|{group}")
        accumulators.append(accumulator)

    all_edges: list[Edge] = []
    for accumulator in accumulators:
        all_edges.extend(accumulator.edges())
    merged_edges = _merge_edges(all_edges) if filters.include_union else all_edges

    merged_edges = [edge for edge in merged_edges if edge.weight >= filters.min_edge_weight]
    merged_edges = [edge for edge in merged_edges
                    if _in_range(edge, filters.start_time, filters.end_time)]
    merged_edges.sort(key=lambda e: (-e.weight, e.first_time or 0, e.id))

    for node in nodes.values():
        node.datasets = sorted(set(node.datasets))
    for edge in merged_edges:
        for person_id in (edge.source, edge.target):
            node = nodes.get(person_id)
            if node is None:
                continue
            if edge.relation == "call":
                node.call_count += edge.weight
            elif edge.relation == "sms":
                node.sms_count += edge.weight
            elif edge.relation.startswith("im_"):
                node.message_count += edge.weight
            if edge.first_time and (node.first_time is None or edge.first_time < node.first_time):
                node.first_time = edge.first_time
            if edge.last_time and (node.last_time is None or edge.last_time > node.last_time):
                node.last_time = edge.last_time

    degree: dict[str, int] = {}
    for edge in merged_edges:
        degree[edge.source] = degree.get(edge.source, 0) + edge.weight
        degree[edge.target] = degree.get(edge.target, 0) + edge.weight
    ordered = sorted(nodes.values(),
                     key=lambda n: (not n.is_owner, -degree.get(n.id, 0), n.label))
    kept_nodes = ordered[:filters.max_nodes]
    kept_ids = {node.id for node in kept_nodes}
    visible_edges = [edge for edge in merged_edges
                     if edge.source in kept_ids and edge.target in kept_ids]
    edges_truncated = len(merged_edges) - len(visible_edges)
    if len(visible_edges) > filters.max_edges:
        edges_truncated += len(visible_edges) - filters.max_edges
        visible_edges = visible_edges[:filters.max_edges]

    communities = _communities(kept_nodes, visible_edges) if filters.communities else []
    metrics = _metrics(kept_nodes, visible_edges, communities) if filters.communities else {}

    coverage.update({
        "nodes_total": len(nodes),
        "nodes_shown": len(kept_nodes),
        "nodes_truncated": len(ordered) - len(kept_nodes),
        "edges_total": len(merged_edges),
        "edges_shown": len(visible_edges),
        "edges_truncated": edges_truncated,
        "truncated_sources": len(set(truncated)),
        "truncated_source_ids": sorted(set(truncated)),
        "identity_policy": "strong_keys_only",
        "identity_keys": ["phone", "wxid", "uin"],
    })
    return UnifiedGraph(
        nodes=kept_nodes,
        edges=visible_edges,
        communities=communities,
        coverage=coverage,
        metrics=metrics,
        datasets=datasets_payload,
        candidates=candidates,
        filters=filters.model_dump(),
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_contacts(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
                   coverage: dict[str, int]) -> None:
    for row in _guarded(read_contacts, conn, ref.dataset_id, limit=MAX_ROWS_PER_SOURCE):
        coverage["contacts_read"] += 1
        phone = normalize_phone(row["phone"])
        name = row["name"].strip()
        if phone:
            matcher.observe("phone", phone, label=name, dataset=ref.dataset_id, alias=name)
        elif name:
            # A contact without a number is a name-only identity. It stays
            # visible in the contact list but is never merged into a phone
            # identity automatically.
            matcher.observe("name", name.casefold(), label=name,
                            dataset=ref.dataset_id, alias=name)


def _load_chatrooms(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
                    coverage: dict[str, int],
                    group_members: dict[tuple[str, str], set[str]],
                    group_labels: dict[tuple[str, str], str]) -> None:
    for row in _guarded(read_wechat_chatrooms, conn, ref.dataset_id,
                        limit=MAX_ROWS_PER_SOURCE):
        coverage["contacts_read"] += 1
        group = row["group"]
        key = (ref.dataset_id, group)
        members = group_members.setdefault(key, set())
        for member in row.get("members", []):
            wxid = normalize_wxid(member)
            if not wxid:
                continue
            matcher.observe("wxid", wxid, dataset=ref.dataset_id)
            members.add(wxid)
        group_labels[key] = group


def _load_wechat(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
                 coverage: dict[str, int], accumulators: list[EdgeAccumulator],
                 owner_username: str, owner_id: str,
                 group_members: dict[tuple[str, str], set[str]],
                 truncated: list[str]) -> None:
    accumulator = EdgeAccumulator(owner_id)

    for row in _guarded(read_wechat_contacts, conn, ref.dataset_id,
                        limit=MAX_ROWS_PER_SOURCE):
        coverage["contacts_read"] += 1
        wxid = normalize_wxid(row["wxid"])
        if not wxid:
            continue
        key = matcher.observe("wxid", wxid, label=row["name"], dataset=ref.dataset_id,
                              alias=row["name"])
        phone = normalize_phone(row.get("phone"))
        if phone:
            # The device user stored this number for the contact; that is an
            # explicit source record, so the merge is evidence-backed rather
            # than name guessing.
            matcher.link(key, matcher.observe("phone", phone, label=row["name"],
                                              dataset=ref.dataset_id, alias=row["name"]))

    count = 0
    for row in _guarded(read_wechat_messages, conn, ref.dataset_id,
                        limit=MAX_ROWS_PER_SOURCE, owner_username=owner_username):
        count += 1
        if row["kind"] == "im_group":
            group = row["group"]
            key = (ref.dataset_id, group)
            group_members.setdefault(key, set())
            sender_wxid = normalize_wxid(row["sender"])
            if sender_wxid:
                group_members[key].add(sender_wxid)
            sender_key = matcher.observe("wxid", sender_wxid, dataset=ref.dataset_id)
            if sender_wxid and sender_wxid == owner_username:
                matcher.link(sender_key, matcher.root(f"owner:{ref.dataset_id}") and
                             f"owner:{ref.dataset_id}")
            group_id = "g_" + digest([ref.dataset_id, group])[:24]
            accumulator.add(source=matcher.person_id(sender_key), target=group_id,
                            relation="im_group", dataset=ref.dataset_id,
                            direction="unknown", timestamp=row["timestamp"],
                            media=row["media"], sample=row["content"],
                            record_ref=row["ref"])
            continue

        sender_wxid = normalize_wxid(row["sender"])
        receiver_wxid = normalize_wxid(row["receiver"])
        sender_key = matcher.observe("wxid", sender_wxid, dataset=ref.dataset_id)
        receiver_key = matcher.observe("wxid", receiver_wxid, dataset=ref.dataset_id)
        sender_id = matcher.person_id(sender_key)
        receiver_id = matcher.person_id(receiver_key)
        direction = "sent" if sender_id == owner_id else "received"
        accumulator.add(source=sender_id, target=receiver_id, relation="im_private",
                        dataset=ref.dataset_id, direction=direction,
                        timestamp=row["timestamp"], media=row["media"],
                        sample=row["content"], record_ref=row["ref"])
    coverage["messages_read"] += count
    if count >= MAX_ROWS_PER_SOURCE:
        truncated.append(ref.dataset_id)
    accumulators.append(accumulator)


def _load_calls(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
                coverage: dict[str, int], accumulators: list[EdgeAccumulator],
                owner_id: str, truncated: list[str]) -> None:
    accumulator = EdgeAccumulator(owner_id)
    count = 0
    for row in _guarded(read_call_logs, conn, ref.dataset_id, limit=MAX_ROWS_PER_SOURCE):
        count += 1
        phone = normalize_phone(row["phone"])
        if not phone:
            coverage["orphan_records"] += 1
            continue
        key = matcher.observe("phone", phone, label=row["name"], dataset=ref.dataset_id,
                              alias=row["name"])
        peer_id = matcher.person_id(key)
        source, target = (owner_id, peer_id) if row["direction"] == "sent" else (peer_id, owner_id)
        accumulator.add(source=source, target=target, relation="call",
                        dataset=ref.dataset_id, direction=row["direction"],
                        timestamp=row["timestamp"],
                        duration=row["duration"] if row["connected"] else 0,
                        record_ref=row["ref"])
    coverage["calls_read"] += count
    if count >= MAX_ROWS_PER_SOURCE:
        truncated.append(ref.dataset_id)
    accumulators.append(accumulator)


def _load_sms(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
              coverage: dict[str, int], accumulators: list[EdgeAccumulator],
              owner_id: str, truncated: list[str]) -> None:
    accumulator = EdgeAccumulator(owner_id)
    count = 0
    for row in _guarded(read_sms, conn, ref.dataset_id, limit=MAX_ROWS_PER_SOURCE):
        count += 1
        phone = normalize_phone(row["phone"])
        if not phone:
            coverage["orphan_records"] += 1
            continue
        key = matcher.observe("phone", phone, label=row["name"], dataset=ref.dataset_id,
                              alias=row["name"])
        peer_id = matcher.person_id(key)
        source, target = (owner_id, peer_id) if row["direction"] == "sent" else (peer_id, owner_id)
        accumulator.add(source=source, target=target, relation="sms",
                        dataset=ref.dataset_id, direction=row["direction"],
                        timestamp=row["timestamp"], sample=row["body"],
                        record_ref=row["ref"])
    coverage["sms_read"] += count
    if count >= MAX_ROWS_PER_SOURCE:
        truncated.append(ref.dataset_id)
    accumulators.append(accumulator)


def _load_artifacts(conn: sqlite3.Connection, ref: DatasetRef, matcher: Matcher,
                    coverage: dict[str, int], accumulators: list[EdgeAccumulator],
                    owner_id: str, truncated: list[str]) -> None:
    accumulator = EdgeAccumulator(owner_id)
    count = 0
    for row in _guarded(read_mobile_artifacts, conn, ref.dataset_id,
                        limit=MAX_ROWS_PER_SOURCE):
        count += 1
        phone = normalize_phone(row.get("phone"))
        sender = normalize_wxid(row.get("sender"))
        receiver = normalize_wxid(row.get("receiver"))
        peer_key = None
        if phone:
            peer_key = matcher.observe("phone", phone, label=row.get("name", ""),
                                       dataset=ref.dataset_id)
        elif sender or receiver:
            peer_key = matcher.observe("wxid", sender or receiver,
                                       dataset=ref.dataset_id)
        peer_id = matcher.person_id(peer_key)
        if peer_id is None:
            coverage["orphan_records"] += 1
            continue
        accumulator.add(source=owner_id, target=peer_id, relation="im_private",
                        dataset=ref.dataset_id, direction="unknown",
                        timestamp=row["timestamp"], sample=row.get("content", ""),
                        record_ref=row["ref"])
    coverage["artifacts_read"] += count
    if count >= MAX_ROWS_PER_SOURCE:
        truncated.append(ref.dataset_id)
    accumulators.append(accumulator)


__all__ = ["CommGraphService"]
