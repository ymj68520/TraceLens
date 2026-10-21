import asyncio

from ..people_graph.models import digest
from ..people_graph.sources import source_changes
from ..people_graph.storage import RunConflict
from .inference import analyze, bind_people
from .models import OPERATION, POLICY_VERSION, PROMPT_VERSION
from .snapshot import read_snapshot, projection


class EventGraphService:
    """Shares the people manager's owner epoch, queue, admission and shutdown."""
    def __init__(self, manager):
        self.manager = manager

    async def _snapshot(self, task_id):
        task, store = await self.manager._scope(task_id)
        return task, store, await asyncio.to_thread(read_snapshot, store.path, task_id)

    async def live(self, task_id, filters):
        _, _, snapshot = await self._snapshot(task_id)
        return projection(snapshot, filters)

    async def _run(self, task_id, run_id):
        task, store = await self.manager._scope(task_id)
        run = await asyncio.to_thread(store.get, run_id)
        if not run or run["operation"] != OPERATION:
            raise FileNotFoundError("事件关联版本不属于当前任务")
        return task, store, run

    async def list_runs(self, task_id):
        _, store = await self.manager._scope(task_id)
        return [self.manager._public(r) for r in await asyncio.to_thread(store.list, (OPERATION,))]

    async def start(self, request, actor):
        m = self.manager
        if not m._accepting:
            raise RunConflict("服务正在关闭")
        task, store, snapshot = await self._snapshot(request.task_id)
        if not snapshot["events"]:
            raise ValueError("当前没有已登记调查事件；请先在调查工作台登记事件")
        available = {e["event_id"] for e in snapshot["events"]}
        selected = request.event_ids or [e["event_id"] for e in snapshot["events"][:50]]
        if len(set(selected)) != len(selected) or not set(selected) <= available:
            raise ValueError("事件选择重复或不属于本轮可读取的任务事件")
        base = None
        if request.people_run_id:
            _, _, base = await m._run(request.task_id, request.people_run_id)
            if base["status"] != "completed":
                raise ValueError("请选择当前任务已完成的人员版本")
        # Hold admission while capturing bindings, so concurrent submissions
        # cannot enqueue unbounded byte checks. No model calls occur here.
        async with m._admission:
            if not m._accepting:
                raise RunConflict("服务正在关闭")
            running = await asyncio.to_thread(store.list)
            if any(r["status"] == "running" and r["owner_epoch"] == m.epoch for r in running):
                raise RunConflict("当前任务已有图谱分析在运行")
            scoped = {**snapshot, "events": [e for e in snapshot["events"] if e["event_id"] in selected]}
            people = await bind_people(task, scoped, base)
            frozen = {**request.model_dump(), "snapshot": snapshot, "snapshot_hash": digest(snapshot),
                      "selected_event_ids": selected, "people": people,
                      "people_result_hash": base["result_hash"] if base else None,
                      "task_case_hash": digest(task.get("case_description") or ""),
                      "policy_version": POLICY_VERSION, "prompt_version": PROMPT_VERSION}
            run = await asyncio.to_thread(store.admit, frozen, actor, m.epoch, OPERATION, request.people_run_id)
            m.launch(store, run, self._execute(store, run))
        return m._public(run)

    async def _execute(self, store, run):
        async def progress(phase, value):
            await asyncio.to_thread(store.progress, run["run_id"], phase, value)
        try:
            async with self.manager._slots, asyncio.timeout(1800):
                result = await analyze(run["input"], self.manager.llm, progress)
                result["coverage"].update(selected_events=len(run["input"]["selected_event_ids"]),
                    events_not_selected=len(run["input"]["snapshot"]["events"]) - len(run["input"]["selected_event_ids"]))
                await asyncio.to_thread(store.finish, run["run_id"], result)
        except asyncio.CancelledError:
            await asyncio.to_thread(store.finish, run["run_id"], error="事件关联分析已取消", cancelled=True)
        except Exception as exc:
            await asyncio.to_thread(store.finish, run["run_id"], error=f"事件关联分析未完成（{type(exc).__name__}），已有版本保留")

    async def freshness(self, task, store, run):
        frozen = run["input"]
        state = {"investigation": "unavailable", "people_materials": "not_selected",
                 "task_case_changed": frozen["task_case_hash"] != digest(task.get("case_description") or "")}
        try:
            current = await asyncio.to_thread(read_snapshot, store.path, task["id"])
            state["investigation"] = "unchanged" if digest(current) == frozen["snapshot_hash"] else "changed"
        except Exception:
            pass
        if frozen["people_run_id"]:
            try:
                base = await asyncio.to_thread(store.get, frozen["people_run_id"])
                state["people_materials"] = "changed" if await asyncio.to_thread(source_changes, task, base["result"]) else "unchanged"
                versions = await asyncio.to_thread(store.list, ("discover", "assess", "identity_review"))
                latest = next((r for r in versions if r["status"] == "completed"), None)
                state["newer_people_version"] = bool(latest and latest["run_id"] != base["run_id"])
            except Exception:
                state["people_materials"] = "unavailable"
        return state

    async def status(self, task_id, run_id):
        _, _, run = await self._run(task_id, run_id)
        return self.manager._public(run, True)

    async def graph(self, task_id, run_id, filters):
        task, store, run = await self._run(task_id, run_id)
        if run["status"] != "completed":
            raise RunConflict("分析尚未完成")
        return {**projection(run["input"]["snapshot"], filters, run["result"]), "run": self.manager._public(run, True),
                "analysis_coverage": run["result"]["coverage"], "models": run["result"]["models"],
                "people_run_id": run["input"]["people_run_id"], "people_result_hash": run["input"]["people_result_hash"],
                "freshness": await self.freshness(task, store, run)}

    async def detail(self, task_id, target_id, run_id=None, source_version=None):
        if run_id:
            task, store, run = await self._run(task_id, run_id)
            if run["status"] != "completed":
                raise RunConflict("分析尚未完成")
            snapshot = run["input"]["snapshot"]
            extra = run["result"]
            sources = snapshot["sources"] + run["input"]["people"]["sources"]
            freshness = await self.freshness(task, store, run)
        else:
            _, _, snapshot = await self._snapshot(task_id)
            if not source_version or source_version != digest(snapshot):
                raise RunConflict("当前调查数据已变化，请刷新图谱后回查")
            extra, sources, freshness = {}, snapshot["sources"], {}
        all_nodes = snapshot["nodes"] + extra.get("people_nodes", [])
        all_links = snapshot["links"] + extra.get("links", [])
        target = next((v for v in all_nodes + all_links if v["id"] == target_id), None)
        if target is None:
            raise FileNotFoundError("目标不属于所选图谱版本")
        node_by_id = {n["id"]: n for n in all_nodes}
        target = {**target, "endpoints": [node_by_id[end] for end in (target.get("source"), target.get("target")) if end in node_by_id]}
        related = [e for e in all_links if target_id in (e["source"], e["target"])]
        source_ids = set(target.get("source_ids", []))
        if target.get("kind") == "evidence":
            source_ids.add(target["id"])
        for edge in [target, *related]:
            source_ids.update(edge.get("source_ids", []))
            for endpoint in (edge.get("source", ""), edge.get("target", "")):
                if endpoint.startswith("evidence:"):
                    source_ids.add(endpoint)
        return {"target": target, "relations": related, "sources": [s for s in sources if s["id"] in source_ids],
                "source_version": digest(snapshot), "run_id": run_id, "freshness": freshness}

    async def cancel(self, task_id, run_id):
        _, store, run = await self._run(task_id, run_id)
        handle = self.manager._tasks.get(run_id)
        if handle:
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
        if run["status"] == "running":
            await asyncio.to_thread(store.finish, run_id, error="事件关联分析已取消", cancelled=True)
        return await self.status(task_id, run_id)
