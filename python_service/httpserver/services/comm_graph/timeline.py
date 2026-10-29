"""Case timeline over the unified communication records.

This is an event stream, not the statistical summary in ``timeline_summary``:
every row here is one record with a timestamp, a source, and a reference back
to the original database row. Records without a usable timestamp are counted
in coverage and never fabricated into the stream.

De-duplication is by ``(dataset, table, record_id)`` only. Two datasets that
happen to contain the same text are still two records — collapsing them would
hide that the material exists twice.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Iterator

from .identity import EdgeAccumulator, Matcher
from .models import DatasetRef, digest, normalize_phone, normalize_wxid
from .service import _connect, _guarded, _load_contacts, _load_chatrooms, _load_wechat
from .sources import (
    MAX_ROWS_PER_SOURCE,
    read_call_logs,
    read_mobile_artifacts,
    read_owner,
    read_sms,
    read_wechat_messages,
)

MAX_TIMELINE_RECORDS = 100_000
MAX_TIMELINE_PAGE = 500

_EVENT_KIND_LABELS = {
    "call": "通话",
    "sms": "短信",
    "im_private": "私聊",
    "im_group": "群消息",
    "im_artifact": "IM 记录",
}


@dataclass
class TimelineRecord:
    timestamp: int
    kind: str
    dataset: str
    actor: str
    peer: str
    direction: str
    summary: str
    record_ref: str
    group: str = ""
    # Stable person ids resolved through the same identity rules as the graph,
    # so a record can be traced back to the node it belongs to.
    actor_id: str = ""
    peer_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "kind_label": _EVENT_KIND_LABELS.get(self.kind, self.kind),
            "dataset": self.dataset,
            "actor": self.actor,
            "actor_id": self.actor_id,
            "peer": self.peer,
            "peer_id": self.peer_id,
            "group": self.group,
            "direction": self.direction,
            "summary": self.summary,
            "record_ref": self.record_ref,
        }


def _clip(text: str, limit: int = 200) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit]


class _Resolver:
    """Maps raw identifiers to the same person ids the graph uses.

    Built from the same source readers as ``CommGraphService`` so an id shown
    on the graph is the same id in the timeline and in edge drill-down.
    """

    def __init__(self) -> None:
        self._matcher = Matcher()
        self._owner: dict[str, str] = {}

    def load(self, ref: DatasetRef) -> None:
        dataset_id = ref.dataset_id
        with closing(_connect(ref.path)) as conn:
            owner = read_owner(conn)
            owner_username = normalize_wxid(owner.get("username"))
            owner_key = None
            if owner_username:
                owner_key = self._matcher.observe(
                    "wxid", owner_username,
                    label=owner.get("nickname") or owner_username, dataset=dataset_id)
            if owner_key is None:
                owner_key = self._matcher.observe(
                    "owner", dataset_id, label=f"本机（{ref.label}）", dataset=dataset_id)
            else:
                self._matcher.link(owner_key, self._matcher.observe(
                    "owner", dataset_id, dataset=dataset_id))
            owner_id = self._matcher.person_id(owner_key) or ""
            self._owner[dataset_id] = owner_id
            coverage: dict[str, int] = Counter()
            _load_contacts(conn, ref, self._matcher, coverage)
            _load_chatrooms(conn, ref, self._matcher, coverage, {}, {})
            _load_wechat(conn, ref, self._matcher, coverage, [], owner_username,
                         owner_id, {}, [])

    def owner_id(self, dataset_id: str) -> str:
        return self._owner.get(dataset_id, "")

    def phone_id(self, value: str) -> str:
        phone = normalize_phone(value)
        if not phone:
            return ""
        return self._matcher.person_id(self._matcher.observe("phone", phone)) or ""

    def wxid_id(self, value: str) -> str:
        wxid = normalize_wxid(value)
        if not wxid:
            return ""
        return self._matcher.person_id(self._matcher.observe("wxid", wxid)) or ""

    def group_id(self, dataset_id: str, group: str) -> str:
        return "g_" + digest([dataset_id, group])[:24]


def _iter_records(ref: DatasetRef, resolver: _Resolver) -> Iterator[TimelineRecord]:
    """Yield every timestamped record of one dataset."""
    with closing(_connect(ref.path)) as conn:
        dataset_id = ref.dataset_id
        owner_id = resolver.owner_id(dataset_id)
        for row in _guarded(read_call_logs, conn, dataset_id, limit=MAX_ROWS_PER_SOURCE):
            if not row["timestamp"]:
                continue
            peer_id = resolver.phone_id(row["phone"])
            yield TimelineRecord(
                timestamp=row["timestamp"], kind="call", dataset=dataset_id,
                actor="本机", actor_id=owner_id,
                peer=row["name"] or row["phone"], peer_id=peer_id,
                direction=row["direction"],
                summary=(f"通话 {row['duration']} 秒" if row["connected"]
                         else "未接通"),
                record_ref=row["ref"])
        for row in _guarded(read_sms, conn, dataset_id, limit=MAX_ROWS_PER_SOURCE):
            if not row["timestamp"]:
                continue
            peer_id = resolver.phone_id(row["phone"])
            yield TimelineRecord(
                timestamp=row["timestamp"], kind="sms", dataset=dataset_id,
                actor="本机", actor_id=owner_id,
                peer=row["name"] or row["phone"], peer_id=peer_id,
                direction=row["direction"], summary=_clip(row["body"]),
                record_ref=row["ref"])
        for row in _guarded(read_wechat_messages, conn, dataset_id,
                            limit=MAX_ROWS_PER_SOURCE, owner_username=""):
            if not row["timestamp"]:
                continue
            if row["kind"] == "im_group":
                yield TimelineRecord(
                    timestamp=row["timestamp"], kind="im_group", dataset=dataset_id,
                    actor=row["sender"], actor_id=resolver.wxid_id(row["sender"]),
                    peer=row["group"], peer_id=resolver.group_id(dataset_id, row["group"]),
                    group=row["group"], direction="unknown",
                    summary=_clip(row["content"]), record_ref=row["ref"])
            else:
                yield TimelineRecord(
                    timestamp=row["timestamp"], kind="im_private", dataset=dataset_id,
                    actor=row["sender"], actor_id=resolver.wxid_id(row["sender"]),
                    peer=row["receiver"], peer_id=resolver.wxid_id(row["receiver"]),
                    direction="sent" if row.get("is_send") else "received",
                    summary=_clip(row["content"]), record_ref=row["ref"])
        for row in _guarded(read_mobile_artifacts, conn, dataset_id,
                            limit=MAX_ROWS_PER_SOURCE):
            if not row["timestamp"]:
                continue
            peer_id = (resolver.phone_id(row.get("phone", ""))
                       or resolver.wxid_id(row.get("sender", ""))
                       or resolver.wxid_id(row.get("receiver", "")))
            yield TimelineRecord(
                timestamp=row["timestamp"], kind="im_artifact", dataset=dataset_id,
                actor=row.get("sender") or "未知", actor_id=owner_id,
                peer=row.get("receiver") or row.get("phone", ""), peer_id=peer_id,
                direction="unknown", summary=_clip(row.get("content", "")),
                record_ref=row["ref"])


def _build_resolvers(refs: list[DatasetRef]) -> _Resolver:
    resolver = _Resolver()
    for ref in refs:
        try:
            resolver.load(ref)
        except sqlite3.DatabaseError:
            continue
    return resolver


def build_timeline(refs: list[DatasetRef], *, start_time: int | None = None,
                   end_time: int | None = None, kinds: set[str] | None = None,
                   datasets: set[str] | None = None,
                   limit: int = MAX_TIMELINE_PAGE) -> dict[str, Any]:
    """Merge every dataset into one chronological stream.

    Returns ``{"records": [...], "coverage": {...}}``. Coverage always states
    how many records were scanned, filtered out, and truncated by the page
    limit.
    """
    if limit < 1 or limit > MAX_TIMELINE_PAGE:
        raise ValueError("invalid timeline page limit")
    resolver = _build_resolvers(refs)
    counts: Counter[str] = Counter()
    records: list[TimelineRecord] = []
    seen: set[tuple[str, str]] = set()
    sources: list[dict[str, Any]] = []
    truncated: list[str] = []

    for ref in refs:
        if datasets and ref.dataset_id not in datasets:
            counts["datasets_filtered"] += 1
            continue
        counts["datasets_scanned"] += 1
        scanned = 0
        try:
            for record in _iter_records(ref, resolver):
                scanned += 1
                if scanned > MAX_TIMELINE_RECORDS:
                    truncated.append(ref.dataset_id)
                    break
                counts["records_scanned"] += 1
                if kinds and record.kind not in kinds:
                    counts["filtered_kind"] += 1
                    continue
                if start_time is not None and record.timestamp < start_time:
                    counts["filtered_time"] += 1
                    continue
                if end_time is not None and record.timestamp > end_time:
                    counts["filtered_time"] += 1
                    continue
                key = (ref.dataset_id, record.record_ref)
                if key in seen:
                    counts["duplicates"] += 1
                    continue
                seen.add(key)
                records.append(record)
        except sqlite3.DatabaseError:
            counts["datasets_unreadable"] += 1
            sources.append({"dataset_id": ref.dataset_id, "status": "unreadable"})
            continue
        sources.append({"dataset_id": ref.dataset_id, "status": "read",
                        "records_scanned": scanned})

    records.sort(key=lambda r: (r.timestamp, r.dataset, r.record_ref))
    counts["records_total"] = len(records)
    page = records[:limit]
    counts["records_returned"] = len(page)
    counts["records_truncated"] = len(records) - len(page)
    return {
        "records": [record.as_dict() for record in page],
        "sources": sources,
        "coverage": {
            **counts,
            "truncated_sources": sorted(set(truncated)),
            "dedup_rule": "dataset+record_ref:v1",
            "order": "timestamp_asc_then_dataset_record_ref",
            "filters": {
                "start_time": start_time, "end_time": end_time,
                "kinds": sorted(kinds) if kinds else [],
                "datasets": sorted(datasets) if datasets else [],
            },
        },
    }


def edge_detail(refs: list[DatasetRef], *, source: str, target: str,
                relation: str) -> dict[str, Any]:
    """Records backing one aggregated edge.

    ``source``/``target`` are the person ids shown on the graph; they are
    resolved with the same identity rules, so the drill-down matches the edge
    the analyst clicked.
    """
    resolver = _build_resolvers(refs)
    records: list[dict[str, Any]] = []
    scanned = 0
    endpoints = {source, target}
    for ref in refs:
        try:
            for record in _iter_records(ref, resolver):
                scanned += 1
                if scanned > MAX_TIMELINE_RECORDS:
                    break
                if relation and record.kind != relation:
                    continue
                if {record.actor_id, record.peer_id} != endpoints:
                    continue
                records.append(record.as_dict())
        except sqlite3.DatabaseError:
            continue
    records.sort(key=lambda item: item["timestamp"])
    return {
        "records": records[:MAX_TIMELINE_PAGE],
        "total": len(records),
        "truncated": max(0, len(records) - MAX_TIMELINE_PAGE),
        "source": source, "target": target, "relation": relation,
        "ref": "edge:" + digest([source, target, relation])[:24],
    }


__all__ = [
    "MAX_TIMELINE_RECORDS",
    "MAX_TIMELINE_PAGE",
    "TimelineRecord",
    "build_timeline",
    "edge_detail",
]
