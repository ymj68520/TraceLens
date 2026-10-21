"""One read transaction; exact event narratives and evidence snapshots, no bootstrap."""
from collections import defaultdict
from itertools import combinations

from ..investigation.graph import _project_overlay
from ..investigation.graph_reader import InvestigationGraphReader
from ..investigation.models import InvestigationGraphNode
from ..people_graph.models import digest, stable_id
from .models import POLICY_VERSION

EVENT_LIMIT = 500
SOURCE_LIMIT = 2000
SHARED_LIMIT = 5000


def read_snapshot(path, task_id):
    if not path.is_file():
        return {"task_id": task_id, "events": [], "sources": [], "nodes": [], "links": [],
                "coverage": {"events_total": 0, "events_captured": 0, "evidence_total": 0,
                             "evidence_captured": 0, "store_exists": False, "truncated": False},
                "policy_version": POLICY_VERSION}
    reader = InvestigationGraphReader(path, task_id)

    def read(conn):
        conn.execute("BEGIN")
        overlay = reader._read_with_conn(conn)
        events = list(overlay.events[:EVENT_LIMIT])
        event_ids = {e.event_id for e in events}
        nodes, links = _project_overlay(overlay)
        # Stable source identities are canonical evidence keys, never display names.
        existing_evidence = {n.provenance["evidence_key"] for n in nodes if n.label == "Evidence"}
        evidence_keys = sorted(overlay.evidence_types)
        for key in evidence_keys:
            if key not in existing_evidence:
                nodes.append(InvestigationGraphNode(id=f"evidence:{key}", name=key, label="Evidence",
                             source="investigation", provenance={"evidence_key": key, "evidence_type": overlay.evidence_types[key]}))
        sources, text_left, payload_left = [], 1_000_000, 4_000_000
        for key in evidence_keys[:SOURCE_LIMIT]:
            snapshot = reader._latest_snapshot_with_conn(conn, key)
            if snapshot is None:
                continue
            payload = snapshot.payload.model_dump(mode="json")
            raw_text = "\n".join(str(payload.get(k) or "") for k in ("initial_summary", "initial_description"))
            kind = "initial_analysis_summary"
            if snapshot.evidence_type == "android_artifact":
                import json
                raw_text = json.dumps(payload.get("record_fields", {}), ensure_ascii=False, sort_keys=True)
                kind = "android_record"
            raw_text = raw_text.strip()
            text = raw_text[:min(6000, text_left)]
            text_left -= len(text)
            import json
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            keep_payload = len(encoded) <= min(128_000, payload_left)
            if keep_payload:
                payload_left -= len(encoded)
            sources.append({"id": f"evidence:{key}", "evidence_key": key,
                            "snapshot_hash": digest(payload), "captured_at": snapshot.captured_at,
                            "kind": kind, "evidence_type": snapshot.evidence_type,
                            "payload": payload if keep_payload else None,
                            "payload_truncated": not keep_payload,
                            "text": text, "text_hash": digest(text), "text_truncated": len(text) < len(raw_text),
                            "original_characters": len(raw_text),
                            "name": payload.get("name") or payload.get("normalized_path") or key})
        source_map = {s["evidence_key"]: s for s in sources}
        selected_nodes = []
        for n in nodes:
            if n.label == "InvestigationEvent" and n.provenance["event_id"] not in event_ids:
                continue
            if n.label == "Evidence" and n.provenance["evidence_key"] not in source_map:
                continue
            row = n.model_dump(mode="json")
            row["kind"] = {"InvestigationEvent": "event", "Evidence": "evidence", "Analysis": "analysis", "Claim": "claim"}[n.label]
            if row["kind"] == "evidence":
                row["name"] = source_map[n.provenance["evidence_key"]]["name"]
            selected_nodes.append(row)
        # Events (including isolated ones) take precedence over contextual nodes.
        selected_nodes.sort(key=lambda n: (n["kind"] != "event", n["id"]))
        included_nodes = selected_nodes[:6000]
        ids = {n["id"] for n in included_nodes}
        rows = [l.model_dump(mode="json") for l in links if l.source in ids and l.target in ids]
        for row in rows:
            row["status"] = "recorded"
        by_evidence = defaultdict(list)
        event_sources = defaultdict(list)
        for link in overlay.event_links:
            if link.event_id in event_ids and link.evidence_key in source_map:
                by_evidence[link.evidence_key].append(link.event_id)
                event_sources[link.event_id].append(f"evidence:{link.evidence_key}")
        shared = {}
        for key, event_list in sorted(by_evidence.items()):
            for a, b in combinations(sorted(set(event_list)), 2):
                shared.setdefault((a, b), []).append(f"evidence:{key}")
        for (a, b), refs in list(sorted(shared.items()))[:SHARED_LIMIT]:
            rows.append({"id": stable_id("shared", task_id, a, b), "source": f"event:{a}", "target": f"event:{b}",
                         "kind": "shared_evidence", "label": "共同关联材料", "status": "derived",
                         "source_ids": refs})
        captured_events = [{**e.model_dump(mode="json"), "source_ids": sorted(event_sources[e.event_id])} for e in events]
        return {"task_id": task_id, "events": captured_events, "sources": sources,
                "nodes": included_nodes, "links": rows[:25000], "policy_version": POLICY_VERSION,
                "coverage": {"store_exists": True, "events_total": len(overlay.events), "events_captured": len(events),
                             "evidence_total": len(evidence_keys), "evidence_captured": len(sources),
                             "shared_pairs_total": len(shared), "shared_pairs_captured": min(SHARED_LIMIT, len(shared)),
                             "source_text_truncated": sum(s["text_truncated"] for s in sources),
                             "source_payload_truncated": sum(s["payload_truncated"] for s in sources),
                             "truncated": len(events) < len(overlay.events) or len(sources) < len(evidence_keys)
                                 or len(shared) > SHARED_LIMIT or len(selected_nodes) > 6000 or len(rows) > 25000,
                             "time_policy": "来源时间保留在快照中；文件时间与事件簇时间不视为行为发生时间，不自动推断先后或因果",
                             "deduplication": "事件按task_id+event_id；证据按准确evidence_key；共同材料边按事件对去重"}}
    return reader._run(read)


def projection(snapshot, filters, associations=None):
    nodes, links = snapshot["nodes"], snapshot["links"]
    if filters.view == "events":
        links = [e for e in links if e["kind"] in ("event_evidence", "shared_evidence")]
        attached = {e["target"] for e in links if e["kind"] == "event_evidence"}
        nodes = [n for n in nodes if n["kind"] == "event" or n["id"] in attached]
    elif filters.view == "evidence":
        links = [e for e in links if e["kind"] != "shared_evidence"]
    else:
        nodes = [n for n in nodes if n["kind"] == "event"] + (associations or {}).get("people_nodes", [])
        links = (associations or {}).get("links", [])
    ids = {n["id"] for n in nodes}
    links = [e for e in links if e["source"] in ids and e["target"] in ids]
    if filters.relation_kind:
        links = [e for e in links if e["kind"] == filters.relation_kind]
        ids = {p for e in links for p in (e["source"], e["target"])}
        nodes = [n for n in nodes if n["id"] in ids]
    if filters.query or filters.focus_id:
        anchors = {n["id"] for n in nodes if (not filters.query or filters.query.casefold() in n["name"].casefold())
                   and (not filters.focus_id or n["id"] == filters.focus_id)}
        links = [e for e in links if e["source"] in anchors or e["target"] in anchors]
        ids = anchors | {p for e in links for p in (e["source"], e["target"])}
        nodes = [n for n in nodes if n["id"] in ids]
    names = {n["id"]: n["name"] for n in nodes}
    links = [{**e, "source_name": names[e["source"]], "target_name": names[e["target"]]} for e in links]
    shown = nodes[:filters.max_nodes]
    shown_ids = {n["id"] for n in shown}
    rendered = [e for e in links if e["source"] in shown_ids and e["target"] in shown_ids]
    items = [{**n, "item_type": "node"} for n in nodes] + [{**e, "item_type": "link", "name": e["label"]} for e in links]
    return {"nodes": shown, "links": rendered, "items": items[filters.offset:filters.offset + filters.limit],
            "total_items": len(items), "matched_nodes": len(nodes), "matched_links": len(links),
            "display_truncated": len(shown) < len(nodes) or len(rendered) < len(links),
            "filters": filters.model_dump(), "coverage": snapshot["coverage"],
            "source_version": digest(snapshot), "policy_version": snapshot["policy_version"], "projection_version": POLICY_VERSION,
            "available_events": [{"event_id": e["event_id"], "title": e["title"], "version": e["current_version"]} for e in snapshot["events"]]}
