"""
Multi-image adapter for one global native selection plan.
Task and source identities survive content grouping and shared budget admission.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .file_filter import FileFilter
from .llm_response_parser import LLMResponseParser
from .file_matcher import FileMatcher
from .filter_validator import FilterResultValidator
from ...config import Settings

logger = logging.getLogger(__name__)


class MultiImageFilter(FileFilter):
    """Selects across multiple images with one global finite budget."""

    def __init__(self, settings: Settings, llm_service, cpp_backend):
        """Initialize multi-image filter with enhanced components."""
        super().__init__(settings, llm_service, cpp_backend)
        self._parser = LLMResponseParser(settings)
        self._matcher = FileMatcher(settings)
        self._validator = FilterResultValidator(settings)

    # ── Public API ────────────────────────────────────────────────────────────

    async def filter_files_multi(
        self,
        files_db_paths: List[str],
        case_description: str,
        max_files: int = 400,
        batch_size: int = 50,
        task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Select source references and per-task subsets from one native plan.

        source_counts reports admitted references per task; dedup_removed stays
        zero because grouping never removes original source records.
        """
        if not files_db_paths:
            return {"filtered_files": [], "total_files": 0, "selected_count": 0}

        return await self._filter_files_multi_deterministic(files_db_paths,task_ids,max_files,case_description)

    async def _filter_files_multi_deterministic(
        self,
        files_db_paths: List[str],
        task_ids: Optional[List[str]] = None,
        max_files: int = 0,
        case_context: str = '',
    ) -> Dict[str, Any]:
        """Apply the common policy while retaining each task/source identity."""
        if not task_ids or len(task_ids)!=len(files_db_paths) or self._cpp_backend is None:
            raise ValueError('多镜像选择需要每个已登记任务的来源身份')
        cap=int(getattr(self.settings,'filter_max_files',0) or 0)
        if max_files<0 or cap<0:raise ValueError('文件数量预算不能为负数')
        effective=min([v for v in (max_files,cap) if v>0],default=0)
        plan=(await self._cpp_backend.selection_plan(task_ids,effective,case_context=case_context)
              if case_context else await self._cpp_backend.selection_plan(task_ids,effective))
        if not isinstance(plan,dict) or plan.get('schema_version')!=1 or 'selected' not in plan:
            raise ValueError('多镜像候选选择计划不可用')
        selected=plan['selected']
        if effective and len(selected)>effective:raise ValueError('全局选择计划超出文件数量预算')
        by_task={task:[] for task in task_ids}
        for item in selected:
            if item['task_id'] not in by_task:raise ValueError('选择计划包含其他任务来源')
            by_task[item['task_id']].append(item['reference'])
        for task,database in zip(task_ids,files_db_paths):self._persist_filtered_files(database,task,by_task[task])
        return {'filtered_files':[item['reference'] for item in selected],
            'selected_sources':selected,'per_task':by_task,'reasoning':'按来源身份执行多镜像全局配额，不以同名同大小删除证据',
            'total_files':plan['counts']['indexed'],'selected_count':len(selected),'dedup_removed':0,
            'source_counts':{task:len(items) for task,items in by_task.items()},'plan_id':plan['plan_id'],
            'selection_budget':plan['budget'],'selection_counts':plan['counts'],'model_used':'native_selection',
            'selection_policy':plan.get('policy_version'),'streaming_used':False}

    # ── Internals ─────────────────────────────────────────────────────────────

    def _cross_image_dedup(self, records: List[Dict]) -> List[Dict]:
        """Remove repeated references to the same source, preserving occurrences."""
        # Compatibility helper only removes repeated references to the SAME
        # source. Content grouping belongs to the verified native plan.
        seen=set();unique=[]
        for record in records:
            key=(record.get('source_db') or record.get('task_id'),record.get('source_id'),record['path'])
            if key not in seen:
                seen.add(key);unique.append(record)
        return unique


    def _build_toon_lines(self, records: List[Dict]) -> List[str]:
        """Build TOON-format lines (name | tagged_path | size | category)."""
        lines = []
        for r in records:
            name = Path(r["path"]).name
            tagged = r.get("tagged_path", r["path"])
            size = r.get("size", 0)
            ftype = r.get("file_type", "")
            lines.append(f"{name} | {tagged} | {size} | {ftype}")
        return lines

    async def _run_streaming_filter(
        self,
        schema: str,
        data_lines: List[str],
        case_description: str,
        max_files: int,
        batch_size: int,
        original_records: List[Dict],
    ) -> Dict[str, Any]:
        """Run the streaming batch LLM filter on pre-built TOON data using enhanced pipeline."""
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Build batch_files structure for FileMatcher
        batch_files = []
        for r in original_records:
            batch_files.append({
                "name": Path(r["path"]).name,
                "path": r["path"],
                "size": r.get("size", 0),
                "category": r.get("file_type", ""),
            })

        batches = [data_lines[i:i + batch_size] for i in range(0, len(data_lines), batch_size)]
        all_selected: List[str] = []
        reasonings: List[str] = []

        for idx, batch in enumerate(batches):
            batch_toon = f"{schema}\n" + "\n".join(batch)
            prompt = self._build_batch_filter_prompt(
                case_description=case_description,
                batch_toon=batch_toon,
                batch_number=idx + 1,
                total_batches=len(batches),
                max_files=max_files,
                already_selected=len(all_selected),
            )
            try:
                result = await self._llm_service.analyze(
                    content=batch_toon,
                    model_type="text",
                    prompt=prompt,
                    max_tokens=self.settings.llm_text_max_tokens,
                )
                text = result.get("analysis", {}).get("description", "")

                # Use enhanced parsing pipeline
                parsed = self._parser.parse_filter_response(text, batch_files)
                validated = self._validator.validate_and_repair(parsed, batch_files, max_files=1000)

                all_selected.extend(validated.items)
                if validated.is_valid and validated.warnings:
                    logger.warning(f"[MULTI_FILTER] Batch {idx+1} warnings: {validated.warnings}")
                if len(all_selected) >= max_files:
                    break
            except Exception as e:
                logger.warning(f"[MULTI_FILTER] Batch {idx+1} failed: {e}")

        # Use enhanced duplicate resolution with batch_files
        matched = self._matcher.match_files(all_selected, batch_files, case_description)

        return {
            "filtered_files": matched.files,
            "reasoning": " | ".join(reasonings) if reasonings else "Multi-image filtering completed",
            "selected_count": len(matched.files),
            "streaming_used": True,
        }

    def _distribute_and_persist(
        self,
        selected_tagged: List[str],
        deduped: List[Dict],
        db_paths: List[str],
        task_ids: Optional[List[str]],
    ) -> None:
        """Map selected tagged paths back to per-db file paths and persist."""
        path_to_record = {r.get("tagged_path", r["path"]): r for r in deduped}

        per_db: Dict[str, List[str]] = {db: [] for db in db_paths}
        for tagged in selected_tagged:
            rec = path_to_record.get(tagged)
            if rec:
                per_db[rec["source_db"]].append(rec["path"])

        for idx, (db_path, file_list) in enumerate(per_db.items()):
            # Resolve the task_id for this db: prefer the explicit list,
            # otherwise fall back to extracting it from the db path.
            tid = None
            if task_ids and idx < len(task_ids):
                tid = task_ids[idx]
            else:
                m = re.search(r'tasks/([a-f0-9-]+)/', db_path)
                if m:
                    tid = m.group(1)
            if not tid:
                tid = "_latest"
            self._persist_filtered_files(db_path, tid, file_list)
            logger.info(f"[MULTI_FILTER] Persisted {len(file_list)} files for DB {idx+1}")
