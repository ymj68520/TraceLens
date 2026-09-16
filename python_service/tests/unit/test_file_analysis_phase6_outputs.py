"""
Phase 6 regression tests: D15 structured output (lenient parser + prompt
sections + persist mapping preference) and D18 task-level endpoints
(estimate computation, run job lifecycle, version-chain listing).
"""

import asyncio
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from fastapi import FastAPI

from httpserver.prompts import (
    CASE_FILE_ANALYSIS_TEMPLATE,
    STRUCTURED_OUTPUT_INSTRUCTION,
    TEXT_ANALYSIS_USER_TEMPLATE,
    parse_structured_analysis,
)
from httpserver.routes import file_analysis as fa_route
from httpserver.routes.file_analysis import (
    FileAnalysisEstimateRequest,
    FileAnalysisRunRequest,
    estimate_file_analysis,
    run_file_analysis,
)
from httpserver.services.case_analysis.file_schema import (
    ensure_file_analysis_schema,
    list_analyses,
)

STRUCTURED_SAMPLE = """1. 简要总结
这是一份涉案转账记录，涉及三个账户。

2. 详细分析
表格记录了2024年1月至3月间的转账流水，收款人重复出现。

3. 关键词
转账, 账户A, 账户B、洗钱;资金流水

4. 取证价值
高：直接记录资金转移链条。"""

UNSTRUCTURED_SAMPLE = "这是一份没有遵循格式要求的普通分析文本，第一行就是摘要。"


class TestLenientParser:
    def test_structured_extraction(self):
        parsed = parse_structured_analysis(STRUCTURED_SAMPLE)
        assert parsed["structured"] is True
        assert "转账记录" in parsed["summary"]
        assert parsed["keywords"] == ["转账", "账户A", "账户B", "洗钱", "资金流水"]
        assert "高" in parsed["value"]
        # Full text is never dropped
        assert parsed["description"] == STRUCTURED_SAMPLE

    def test_unstructured_degrades(self):
        parsed = parse_structured_analysis(UNSTRUCTURED_SAMPLE)
        assert parsed["structured"] is False
        assert parsed["summary"].startswith("这是一份")
        assert parsed["description"] == UNSTRUCTURED_SAMPLE
        assert parsed["keywords"] == []

    def test_empty_input(self):
        parsed = parse_structured_analysis("")
        assert parsed["description"] == ""
        assert parsed["structured"] is False

    def test_partial_sections(self):
        text = "1. 简要总结\n只有第一段。\n3. 关键词\n甲、乙"
        parsed = parse_structured_analysis(text)
        assert parsed["structured"] is True
        assert parsed["summary"] == "只有第一段。"
        assert parsed["keywords"] == ["甲", "乙"]
        assert parsed["value"] == ""

    def test_prompt_templates_carry_instruction(self):
        assert "简要总结" in TEXT_ANALYSIS_USER_TEMPLATE
        rendered = CASE_FILE_ANALYSIS_TEMPLATE.format(
            case_description="c", file_path="/a", content="x"
        )
        assert "取证价值" in rendered

    def test_instruction_block_shape(self):
        assert "1. 简要总结" in STRUCTURED_OUTPUT_INSTRUCTION


def _make_files_db(tmp_path):
    db = str(tmp_path / "t_files.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, md5 TEXT,"
        " mtime INTEGER, ctime INTEGER, llm_summary TEXT, llm_description"
        " TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, llm_model_used"
        " TEXT)"
    )
    for i in range(4):
        conn.execute("INSERT INTO files (path, md5) VALUES (?, ?)",
                     (f"/data/f{i}.txt", f"md5{i}"))
    conn.commit()
    conn.close()
    ensure_file_analysis_schema(db)
    return db


class TestEstimateEndpoint:
    async def test_counts_and_cost(self, tmp_path):
        db = _make_files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO file_analyses (task_id, file_path, md5,"
                " description, trigger_source, created_at) VALUES (?, ?, '',"
                " 'd', 'pipeline', 1)",
                [("t1", "/data/f0.txt"), ("t1", "/data/f1.txt")],
            )
            conn.commit()

        service_manager = MagicMock()
        service_manager.cpp_backend.get_task = AsyncMock(
            return_value={"output_files_db": db, "extraction_directory": ""}
        )
        settings = SimpleNamespace(file_analysis_max_content=10000)

        with patch("httpserver.services.get_service_manager",
                   return_value=service_manager):
            with patch(
                "httpserver.services.case_analysis.db_utils.get_filtered_files_from_db",
                return_value=[f"/data/f{i}.txt" for i in range(4)],
            ):
                result = await estimate_file_analysis(
                    FileAnalysisEstimateRequest(task_id="t1"), settings
                )

        assert result["filtered_total"] == 4
        assert result["analyzed"] == 2
        assert result["pending"] == 2
        assert result["estimated_llm_calls"] == 2
        assert result["estimated_chars"] == 20000

    async def test_missing_task_404(self):
        service_manager = MagicMock()
        service_manager.cpp_backend.get_task = AsyncMock(return_value=None)
        with patch("httpserver.services.get_service_manager",
                   return_value=service_manager):
            try:
                await estimate_file_analysis(
                    FileAnalysisEstimateRequest(task_id="ghost"),
                    SimpleNamespace(file_analysis_max_content=10000),
                )
                assert False, "expected 404"
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 404


class TestRunEndpoint:
    async def test_run_lifecycle(self, tmp_path):
        db = _make_files_db(tmp_path)
        case_service = MagicMock()
        case_service.generate_file_descriptions = AsyncMock(
            return_value=[{"file_path": "/data/f0.txt", "success": True}]
        )
        service_manager = MagicMock()
        service_manager.cpp_backend.get_task = AsyncMock(
            return_value={"output_files_db": db,
                          "extraction_directory": str(tmp_path / "ext")}
        )

        with patch(
            "httpserver.routes.case_analysis_endpoints._helpers.get_case_analysis_service",
            return_value=case_service,
        ):
            with patch("httpserver.services.get_service_manager",
                       return_value=service_manager):
                started = await run_file_analysis(
                    FileAnalysisRunRequest(
                        task_id="t1",
                        file_paths=["/data/f0.txt", "/data/f1.txt"],
                        case_description="案情",
                    )
                )

        job = fa_route._run_jobs[started["job_id"]]
        for _ in range(100):
            if job["status"] != "running":
                break
            await asyncio.sleep(0.02)

        assert job["status"] == "completed"
        assert job["total"] == 2
        assert job["results"][0]["success"] is True
        # The case service received the threaded task context (D14/P2 wiring)
        kwargs = case_service.generate_file_descriptions.await_args.kwargs
        assert kwargs["task_id"] == "t1"
        assert kwargs["extraction_dir"] == str(tmp_path / "ext")

    async def test_no_candidates_400(self, tmp_path):
        db = _make_files_db(tmp_path)
        service_manager = MagicMock()
        service_manager.cpp_backend.get_task = AsyncMock(
            return_value={"output_files_db": db, "extraction_directory": ""}
        )
        with patch("httpserver.services.get_service_manager",
                   return_value=service_manager):
            with patch(
                "httpserver.services.case_analysis.db_utils.get_filtered_files_from_db",
                return_value=[],
            ):
                try:
                    await run_file_analysis(
                        FileAnalysisRunRequest(task_id="t1")
                    )
                    assert False, "expected 400"
                except Exception as exc:
                    assert getattr(exc, "status_code", None) == 400


class TestVersionChain:
    def test_list_analyses(self, tmp_path):
        db = _make_files_db(tmp_path)
        with sqlite3.connect(db) as conn:
            for i, path in enumerate(["/data/f0.txt", "/data/f0.txt",
                                      "/data/f1.txt"]):
                conn.execute(
                    "INSERT INTO file_analyses (task_id, file_path, md5,"
                    " description, trigger_source, created_at)"
                    " VALUES ('t1', ?, '', ?, 'pipeline', ?)",
                    (path, f"d{i}", i),
                )
            conn.commit()

        chain = list_analyses(db, "t1", file_path="/data/f0.txt")
        assert [r["description"] for r in chain] == ["d1", "d0"]  # newest first
        assert len(list_analyses(db, "t1")) == 3
        assert list_analyses(str(tmp_path / "nope.db"), "t1") == []


# TestClient smoke: the router mounts and estimate is reachable
def test_router_mounts():
    app = FastAPI()
    app.include_router(fa_route.router)
    client = TestClient(app)
    # 422 (missing body) proves routing + validation are wired
    resp = client.post("/file-analysis/estimate", json={})
    assert resp.status_code == 422
