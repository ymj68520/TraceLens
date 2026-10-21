"""Pure query/identity operations on immutable stored analysis versions."""
from __future__ import annotations

from copy import deepcopy

from .inference import project_identities, unassessed
from .models import stable_id

LEVELS = {"P1": 0, "P2": 1, "P3": 2, "unassessed": 3}


def annotation(result, target):
    return result.get("annotations", {}).get(target, unassessed())


def matches(a, filters):
    p = a["priority"]
    if filters.priority == "core":
        if not a.get("core"):
            return False
    elif filters.priority == "P1_P2":
        if p not in ("P1", "P2"):
            return False
    elif filters.priority != "all" and p != filters.priority:
        return False
    return not filters.question_id or any(r["question_id"] == filters.question_id for r in a.get("relations", []))


def rank(row):
    a = row["assessment"]
    return (not a.get("core", False), LEVELS.get(a["priority"], 3), row.get("name", row.get("label", "")), row["id"])


def project(result, filters):
    if filters.question_id and filters.question_id not in {q["question_id"] for q in result["questions"]}:
        raise ValueError("待核问题不属于本轮评估")
    if filters.view == "relations":
        if filters.priority == "core" or filters.identity_status != "all" or filters.material_id:
            raise ValueError("该筛选仅适用于人员视图")
        edges = [{**r, "assessment": annotation(result, r["id"])} for r in result.get("graph_relations", [])]
        edges = [r for r in edges if matches(r["assessment"], filters)
                 and (not filters.relation_kind or r["label"] == filters.relation_kind)
                 and (not filters.relation_label or r["label"] == filters.relation_label)
                 and (not filters.query or filters.query.casefold() in
                      f"{r['source_name']} {r['target_name']} {r['fact']}".casefold())]
        if filters.focus_id:
            edges = [r for r in edges if filters.focus_id in (r["source"], r["target"])]
        edges.sort(key=rank)
        nodes, rendered = {}, []
        for r in edges:
            added = {r["source"], r["target"]} - set(nodes)
            if len(nodes) + len(added) > filters.max_nodes:
                continue
            for end in ("source", "target"):
                nodes[r[end]] = {"id": r[end], "name": r[f"{end}_name"], "kind": "entity",
                                 "assessment": unassessed("节点仅为所选关系的端点，不继承关系优先级")}
            rendered.append(r)
        return {"nodes": list(nodes.values()), "links": rendered, "items": edges[filters.offset:filters.offset + filters.limit],
                "total_items": len(edges), "matched_nodes": len({p for r in edges for p in (r["source"], r["target"])}),
                "matched_relations": len(edges), "display_truncated": len(rendered) < len(edges)}
    mentions = {m["id"]: m for m in result["mentions"]}
    people = [{**p, "kind": "person", "assessment": annotation(result, p["id"]),
               "mention_count": len(p["mention_ids"]),
               "material_ids": sorted({mentions[mid]["material_id"] for mid in p["mention_ids"]})} for p in result["people"]]
    edges = [{**r, "assessment": annotation(result, r["id"])} for r in result["person_relations"]
             if (r["kind"] == filters.relation_kind if filters.relation_kind else r["kind"] in ("direct", "hypothesis"))
             and (not filters.relation_label or r["label"] == filters.relation_label)]
    selected = [p for p in people if matches(p["assessment"], filters)
                and (not filters.query or any(filters.query.casefold() in n.casefold() for n in p["names"]))
                and (not filters.material_id or filters.material_id in p["material_ids"])
                and (filters.identity_status != "ambiguous" or p["same_name_candidates"] or p["identity_status"] == "identity_conflict")
                and (filters.identity_status != "isolated" or p["relation_count"] == 0)]
    if filters.relation_kind or filters.relation_label:
        involved = {p for r in edges for p in (r["source"], r["target"])}
        selected = [p for p in selected if p["id"] in involved]
    if filters.focus_id:
        if filters.focus_id not in {p["id"] for p in people}:
            raise ValueError("查看中心不属于本轮人员")
        adjacent = {filters.focus_id}
        for r in edges:
            if filters.focus_id in (r["source"], r["target"]):
                adjacent.update((r["source"], r["target"]))
        selected = [p for p in selected if p["id"] in adjacent]
    selected.sort(key=rank)
    core_ids = {p["id"] for p in selected}
    context_ids = set()
    if filters.include_context:
        for r in edges:
            if core_ids.intersection((r["source"], r["target"])):
                context_ids.update((r["source"], r["target"]))
        context_ids -= core_ids
    display = selected + [{**p, "context_only": True} for p in sorted(people, key=rank) if p["id"] in context_ids]
    display = display[:filters.max_nodes]
    shown = {p["id"] for p in display}
    links, matching_links = [], 0
    included = core_ids | context_ids
    for r in edges:
        if r["source"] not in included or r["target"] not in included:
            continue
        qualifies = matches(r["assessment"], filters) and r["source"] in core_ids and r["target"] in core_ids
        if qualifies or filters.include_context:
            matching_links += 1
            if r["source"] in shown and r["target"] in shown:
                links.append({**r, "context_only": not qualifies})
    return {"nodes": display, "links": links, "items": selected[filters.offset:filters.offset + filters.limit],
            "total_items": len(selected), "matched_nodes": len(core_ids | context_ids),
            "matched_relations": matching_links, "display_truncated": len(core_ids | context_ids) > len(display)}


def identity_revision(result, request, actor, revision_id):
    updated = deepcopy(result)
    by_id = {p["id"]: p for p in updated["people"]}
    if len(set(request.person_ids)) != len(request.person_ids) or any(pid not in by_id for pid in request.person_ids):
        raise ValueError("人员标识不属于本轮结果或重复")
    selected = [by_id[pid] for pid in request.person_ids]
    if request.operation == "merge":
        if len(selected) < 2:
            raise ValueError("合并需要至少两个人员候选")
        numbers = {n for p in selected for n in p["identity_numbers"]}
        if len(numbers) > 1:
            raise ValueError("存在不同身份号码，不能直接合并；请先核查来源")
        merged = {
            "id": stable_id("person", revision_id, request.person_ids), "name": request.display_name or selected[0]["name"],
            "names": sorted({n for p in selected for n in p["names"]} | ({request.display_name} if request.display_name else set())),
            "mention_ids": sorted({m for p in selected for m in p["mention_ids"]}),
            "identity_status": "manually_grouped", "identity_numbers": sorted(numbers),
        }
        updated["people"] = [p for p in updated["people"] if p["id"] not in request.person_ids] + [merged]
    else:
        if len(selected) != 1:
            raise ValueError("每次只拆分一个人员候选")
        person = selected[0]
        part = set(request.mention_ids)
        if len(part) != len(request.mention_ids):
            raise ValueError("提及标识不能重复")
        original = set(person["mention_ids"])
        if not part or not part < original:
            raise ValueError("请选择部分提及，保留至少一条在原候选中")
        mentions = {m["id"]: m for m in updated["mentions"]}
        split = []
        for index, ids in enumerate((original - part, part)):
            names = sorted({mentions[mid]["name"] for mid in ids})
            split.append({"id": stable_id("person", revision_id, index), "name": names[0], "names": names,
                          "mention_ids": sorted(ids), "identity_status": "manually_separated",
                          "identity_numbers": sorted({mentions[mid]["identity_number"] for mid in ids if mentions[mid]["identity_number"]})})
        updated["people"] = [p for p in updated["people"] if p["id"] != person["id"]] + split
    updated["people"], updated["person_relations"] = project_identities(
        updated["people"], updated["mentions"], updated["mention_relations"])
    # A changed identity partition cannot silently inherit previous person scores.
    keep = {r["id"] for r in updated.get("graph_relations", [])}
    updated["annotations"] = {k: v for k, v in updated.get("annotations", {}).items() if k in keep}
    updated["identity_history"] = [*updated.get("identity_history", []), {
        **request.model_dump(exclude={"reviewer"}), "actor": actor, "revision": revision_id}]
    updated["assessment_coverage"] = {"reason": "身份分组已调整，请重新评估人物及人员关系",
                                      "pending": len(updated["people"]) + len(updated["person_relations"])}
    updated["coverage"].update(
        people=len(updated["people"]), ambiguous_people=sum(bool(p["same_name_candidates"]) or p["identity_status"] == "identity_conflict" for p in updated["people"]),
        person_relations=len(updated["person_relations"]))
    return updated
