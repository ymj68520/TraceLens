from __future__ import annotations

import asyncio
import copy
import time
import uuid
from collections import Counter

from ..investigation.paths import investigation_db_path_for_task
from .inference import assess, build_people, discover, project_identities
from .models import POLICY_VERSION, DISCOVERY_PROMPT, PRIORITY_PROMPT, digest
from .projection import annotation, identity_revision, project
from .sources import read_materials, source_changes
from .storage import PeopleGraphStore, RunConflict, now


class PeopleGraphService:
    """Optional managed tasks in the existing Python process; no ingestion hook."""
    def __init__(self, cpp_backend, llm, graph_provider):
        self.cpp, self.llm, self.graph_provider = cpp_backend, llm, graph_provider
        self.epoch = uuid.uuid4().hex
        self._tasks = {}
        self._stores = {}
        self._admission = asyncio.Lock()
        self._slots = asyncio.Semaphore(1)
        self._accepting = True
        self._freshness = {}

    async def _scope(self, task_id):
        task = await self.cpp.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise FileNotFoundError("任务不存在")
        return task, PeopleGraphStore(investigation_db_path_for_task(task), task_id)

    def _public(self, run, full=False):
        value = {k: v for k, v in run.items() if k not in ("result", "input", "owner_epoch")}
        frozen = run["input"]
        value.update(case_hash=digest(frozen["case_description"]), policy_version=frozen.get("policy_version", "unrecorded"))
        if full:
            value["case_description"] = frozen["case_description"]
        if run["status"] == "running" and run["owner_epoch"] != self.epoch:
            value.update(status="interrupted", error="上一次服务进程已结束，请重新发起分析")
        return value

    async def list_runs(self, task_id):
        _, store = await self._scope(task_id)
        return [self._public(r) for r in await asyncio.to_thread(store.list)]

    async def _run(self, task_id, run_id):
        task, store = await self._scope(task_id)
        run = await asyncio.to_thread(store.get, run_id)
        if run is None:
            raise FileNotFoundError("分析版本不属于当前任务")
        return task, store, run

    async def _current(self, task, run):
        if run["status"] != "completed":
            return {}
        key = (task["id"], run["run_id"], digest(task.get("case_description") or ""))
        cached = self._freshness.get(key)
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]
        result = run["result"]
        changed = await asyncio.to_thread(source_changes, task, result)
        graph_state = "not_captured"
        if result.get("graph_revision"):
            try:
                current = await asyncio.wait_for(self.graph_provider().get_priority_snapshot(
                    task["id"], result["graph_coverage"]["relation_limit"]), timeout=20)
                graph_state = "changed" if digest(current) != result["graph_revision"] else "unchanged"
            except Exception:
                graph_state = "unavailable"
        value = {"materials_changed": changed,
                 "task_case_changed": digest(task.get("case_description") or "") != run["input"]["task_case_hash"],
                 "graph_state": graph_state, "checked_at": now()}
        if len(self._freshness) > 100:
            self._freshness.clear()
        self._freshness[key] = (time.monotonic(), value)
        return value

    async def status(self, task_id, run_id):
        task, _, run = await self._run(task_id, run_id)
        value = self._public(run, True)
        if run["status"] == "completed":
            value.update(coverage=run["result"]["coverage"],
                         assessment_coverage=run["result"]["assessment_coverage"],
                         graph_coverage=run["result"]["graph_coverage"],
                         freshness=await self._current(task, run))
        return value

    async def start(self, request, actor):
        if not self._accepting:
            raise RunConflict("服务正在关闭")
        task, store = await self._scope(request.task_id)
        base = None
        if request.base_run_id:
            base = await asyncio.to_thread(store.get, request.base_run_id)
            if not base or base["status"] != "completed":
                raise ValueError("基线必须是当前任务已完成的分析版本")
        if request.mode == "assess" and not base:
            raise ValueError("重新评估需要已有人员发现版本")
        context = request.case_description if request.case_description is not None else str(task.get("case_description") or "")
        if len(context) > 8000:
            raise ValueError("案情超过8000字，请明确缩减后提交")
        frozen = {**request.model_dump(), "case_description": context,
                  "task_case_hash": digest(task.get("case_description") or ""),
                  "policy_version": POLICY_VERSION, "discovery_prompt": DISCOVERY_PROMPT,
                  "priority_prompt": PRIORITY_PROMPT, "base_hash": base["result_hash"] if base else None}
        async with self._admission:
            if not self._accepting:
                raise RunConflict("服务正在关闭")
            run = await asyncio.to_thread(store.admit, frozen, actor, self.epoch, request.mode, request.base_run_id)
            handle = asyncio.create_task(self._execute(task, store, run, base))
            self._tasks[run["run_id"]] = handle
            self._stores[run["run_id"]] = store
            def cleanup(_):
                self._tasks.pop(run["run_id"], None)
                self._stores.pop(run["run_id"], None)
            handle.add_done_callback(cleanup)
        return self._public(run)

    async def _execute(self, task, store, run, base):
        rid, frozen = run["run_id"], run["input"]
        async def progress(phase, value):
            await asyncio.to_thread(store.progress, rid, phase, min(99, value))
        try:
            async with self._slots, asyncio.timeout(1800):
                if frozen["mode"] == "discover":
                    materials, coverage, revision, vision_models = await read_materials(
                        task, frozen["max_files"], self.llm, progress)
                    mentions, mention_relations, discovery_coverage, models = await discover(
                        task["id"], materials, self.llm, progress)
                    people, relations = build_people(task["id"], mentions, mention_relations)
                    result = {"materials": materials, "mentions": mentions, "mention_relations": mention_relations,
                              "people": people, "person_relations": relations, "coverage": coverage,
                              "discovery_coverage": discovery_coverage, "catalog_revision": revision,
                              "models": sorted(set(models + vision_models)), "identity_history": [],
                              "graph_relations": [], "graph_episodes": [], "annotations": {},
                              "graph_coverage": {"available": False}, "graph_revision": None,
                              "discovery_prompt": DISCOVERY_PROMPT}
                    if base:
                        self._carry_identity(result, base["result"])
                    try:
                        graph = await asyncio.wait_for(self.graph_provider().get_priority_snapshot(
                            task["id"], frozen["max_graph_relations"]), timeout=20)
                        result.update(graph_relations=graph["relations"], graph_episodes=graph["episodes"],
                                      graph_coverage={**graph["coverage"], "available": True},
                                      graph_revision=digest(graph))
                    except Exception:
                        result["graph_coverage"]["warning"] = "知识图谱暂不可读，人员发现仍保留；关系优先级未覆盖原图"
                else:
                    result = copy.deepcopy(base["result"])
                    if (frozen["case_description"] != base["input"]["case_description"]
                            or base["result"].get("policy_version") != POLICY_VERSION
                            or base["input"].get("priority_prompt") != PRIORITY_PROMPT):
                        result["annotations"] = {}
                score_models = await assess(result, frozen["case_description"], frozen["max_assessments"], self.llm, progress)
                result["models"] = sorted(set(result["models"] + score_models))
                result["case_description"] = frozen["case_description"]
                result["policy_version"] = POLICY_VERSION
                result["priority_prompt"] = PRIORITY_PROMPT
                coverage = result["coverage"]
                counts = Counter(m["status"] for m in result["materials"])
                coverage.update(complete_files=counts["complete"], partial_files=counts["partial"],
                                unavailable_files=counts["unavailable"], identified_mentions=len(result["mentions"]),
                                people=len(result["people"]), ambiguous_people=sum(bool(p["same_name_candidates"]) or p["identity_status"] == "identity_conflict" for p in result["people"]),
                                person_relations=len(result["person_relations"]),
                                exhaustive_people_claim=False)
                await asyncio.to_thread(store.finish, rid, result)
        except asyncio.CancelledError:
            await asyncio.to_thread(store.finish, rid, error="分析已取消或服务关闭", cancelled=True)
        except Exception as error:
            code = type(error).__name__
            await asyncio.to_thread(store.finish, rid, error=f"本轮分析未完成（{code}），既有结果保留")

    @staticmethod
    def _carry_identity(result, old):
        mentions = {m["id"] for m in result["mentions"]}
        carried = [copy.deepcopy(p) for p in old["people"] if p["identity_status"].startswith("manually_")
                   and set(p["mention_ids"]) <= mentions]
        used = {m for p in carried for m in p["mention_ids"]}
        people = []
        for p in result["people"]:
            kept = [m for m in p["mention_ids"] if m not in used]
            if kept:
                people.append({**p, "mention_ids": kept})
        result["people"], result["person_relations"] = project_identities(
            people + carried, result["mentions"], result["mention_relations"])
        result["identity_history"] = copy.deepcopy(old.get("identity_history", []))
        result["coverage"]["identity_groups_carried"] = len(carried)
        result["coverage"]["identity_groups_not_carried"] = sum(
            p["identity_status"].startswith("manually_") for p in old["people"]) - len(carried)

    async def graph(self, task_id, run_id, filters):
        task, _, run = await self._run(task_id, run_id)
        if run["status"] != "completed":
            raise RunConflict("分析尚未完成")
        result = run["result"]
        graph = project(result, filters)
        return {**graph, "run": self._public(run, True), "freshness": await self._current(task, run),
                "coverage": result["coverage"], "graph_coverage": result["graph_coverage"],
                "assessment_coverage": result["assessment_coverage"], "questions": result["questions"],
                "relation_labels": sorted({r["label"] for r in result["person_relations" if filters.view == "people" else "graph_relations"]}),
                "models": result["models"], "identity_history": result["identity_history"],
                "materials": [{k: m[k] for k in ("id", "path", "kind", "status", "limitations",
                                                "original_characters", "processed_characters", "source_hash")} for m in result["materials"]],
                "discovery_coverage": result["discovery_coverage"], "policy_version": result["policy_version"]}

    async def detail(self, task_id, run_id, target_id):
        task, _, run = await self._run(task_id, run_id)
        if run["status"] != "completed":
            raise RunConflict("分析尚未完成")
        result = run["result"]
        people = {p["id"]: p for p in result["people"]}
        mentions = {m["id"]: m for m in result["mentions"]}
        if target_id in people:
            target = {**people[target_id], "kind": "person"}
            selected = [mentions[mid] for mid in target["mention_ids"]]
            refs = [m["ref"] for m in selected]
            relations = [r for r in result["person_relations"] if target_id in (r["source"], r["target"])]
        else:
            target = next((r for r in [*result["person_relations"], *result["graph_relations"]] if r["id"] == target_id), None)
            if target is None:
                raise FileNotFoundError("目标不属于本轮分析")
            selected, relations = [], []
            refs = target.get("refs", [])
            if "episode_ids" in target:
                refs = [{"source_id": e["id"], "quote": e["text"][:1600], "basis_type": e["kind"]}
                        for e in result["graph_episodes"] if e["id"] in target["episode_ids"]]
        sources = {m["id"]: m for m in [*result["materials"], *result["graph_episodes"]]}
        sources_read = []
        for sid in dict.fromkeys(r["source_id"] for r in refs):
            if sid in sources:
                m = sources[sid]
                sources_read.append({k: v for k, v in {**m, "text": m["text"][:12_000],
                    "preview_truncated": len(m["text"]) > 12_000}.items() if not k.startswith("_")})
        return {"target": target, "assessment": annotation(result, target_id), "mentions": selected,
                "refs": refs, "sources": sources_read, "relations": relations,
                "run_id": run_id, "freshness": await self._current(task, run)}

    async def revise_identity(self, task_id, run_id, request, actor):
        task, store, base = await self._run(task_id, run_id)
        if base["status"] != "completed":
            raise RunConflict("只能调整已完成的分析版本")
        if await asyncio.to_thread(source_changes, task, base["result"]):
            raise RunConflict("材料来源已变化，请先重新发现人员")
        frozen = {**base["input"], "identity_decision": request.model_dump(exclude={"reviewer"}),
                  "base_hash": base["result_hash"]}
        # Validate the partition before allocating a durable run.
        revised = identity_revision(base["result"], request, actor, uuid.uuid4().hex)
        async with self._admission:
            if not self._accepting:
                raise RunConflict("服务正在关闭")
            run = await asyncio.to_thread(store.admit, frozen, actor, self.epoch, "identity_review", run_id)
            await asyncio.to_thread(store.finish, run["run_id"], revised)
        return self._public(await asyncio.to_thread(store.get, run["run_id"]))

    async def cancel(self, task_id, run_id):
        _, store, run = await self._run(task_id, run_id)
        handle = self._tasks.get(run_id)
        if handle:
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
            # A task cancelled before its first instruction never enters its
            # exception handler. Close the durable row at this boundary too.
            await asyncio.to_thread(store.finish, run_id, error="分析已取消", cancelled=True)
        elif run["status"] == "running":
            await asyncio.to_thread(store.finish, run_id, error="已结束中断的分析记录", cancelled=True)
        return await self.status(task_id, run_id)

    async def shutdown(self):
        self._accepting = False
        async with self._admission:
            pending = [(rid, task, self._stores[rid]) for rid, task in self._tasks.items()]
        for _, task, _ in pending:
            task.cancel()
        await asyncio.gather(*(task for _, task, _ in pending), return_exceptions=True)
        for rid, _, store in pending:
            await asyncio.to_thread(store.finish, rid, error="服务关闭中断分析", cancelled=True)
