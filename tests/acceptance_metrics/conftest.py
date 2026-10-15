"""Shared harness for the third-party acceptance suite.

Runs against a DEPLOYED TraceLens instance (live services), not in-process
code. Third-party testers only need: two service base URLs, an account, and
the fixture set built by prepare_fixtures.py.

Environment variables
  TRACELENS_CPP_BASE          C++ 后端   (默认 http://127.0.0.1:8666)
  TRACELENS_PY_BASE           Python 服务 (默认 http://127.0.0.1:8090)
  TRACELENS_ACCEPT_USER / _PASSWORD   登录账号（服务开启 field-auth 时必填）
  TRACELENS_ACCEPT_FIXTURES   夹具目录    (默认 tests/acceptance_metrics/fixtures)
  TRACELENS_DATA_DIR          任务库根目录 (默认 <repo>/data)，供直读 SQLite 兜底
  TRACELENS_ACCEPT_TASK_TIMEOUT   单任务完成超时秒 (默认 3600)
  TRACELENS_E01_IMAGE         真实 E01 镜像路径（E01 无法凭空生成）
  TRACELENS_ACCEPT_ASSUME_LLM=1   跳过 LLM 探测，强制运行 LLM 用例
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

CPP_BASE = os.environ.get("TRACELENS_CPP_BASE", "http://127.0.0.1:8666")
PY_BASE = os.environ.get("TRACELENS_PY_BASE", "http://127.0.0.1:8090")
FIXTURE_DIR = Path(os.environ.get("TRACELENS_ACCEPT_FIXTURES", HERE / "fixtures"))
DATA_DIR = Path(os.environ.get("TRACELENS_DATA_DIR", ROOT / "data"))
TASK_TIMEOUT = int(os.environ.get("TRACELENS_ACCEPT_TASK_TIMEOUT", "3600"))

TIMESTAMP = f"accept-{time.strftime('%Y%m%d%H%M%S')}"


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: 用例依赖已配置的 LLM（未配置则跳过）")


class Api:
    """Thin requests wrapper carrying the field-auth bearer token."""

    def __init__(self, token: str | None):
        self.session = requests.Session()
        self.token = token
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, base: str, method: str, path: str, ok=(200, 201, 202),
                **kw) -> tuple[int, dict | list | str]:
        url = base.rstrip("/") + path
        resp = self.session.request(method, url, timeout=120, **kw)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return resp.status_code, body

    def get(self, base: str, path: str, **kw):
        return self.request(base, "GET", path, **kw)

    def post(self, base: str, path: str, **kw):
        return self.request(base, "POST", path, **kw)

    def put(self, base: str, path: str, **kw):
        return self.request(base, "PUT", path, **kw)


@pytest.fixture(scope="session")
def api() -> Api:
    user = os.environ.get("TRACELENS_ACCEPT_USER")
    password = os.environ.get("TRACELENS_ACCEPT_PASSWORD")
    token = None
    if user and password:
        resp = requests.post(f"{PY_BASE}/api/field-auth/login",
                             json={"username": user, "password": password}, timeout=30)
        if resp.status_code != 200:
            pytest.exit(f"field-auth 登录失败({resp.status_code})，请检查 TRACELENS_ACCEPT_USER/PASSWORD", 2)
        token = resp.json()["access_token"]
    client = Api(token)

    for name, base, probe in (("C++ 后端", CPP_BASE, "/api/docs"),
                              ("Python 服务", PY_BASE, "/health")):
        try:
            status, _ = client.get(base, probe)
        except requests.ConnectionError:
            pytest.exit(f"{name}不可达: {base} — 请先启动服务（run.sh 或部署脚本）", 2)
        if status == 401:
            if not token:
                pytest.exit(f"{name}开启了认证，请设置 TRACELENS_ACCEPT_USER/_PASSWORD", 2)
            status, _ = client.get(base, probe)
            assert status == 200, f"{name}认证后仍不可访问({status})"
    return client


@pytest.fixture(scope="session")
def llm_ready(api: Api) -> bool:
    if os.environ.get("TRACELENS_ACCEPT_ASSUME_LLM") == "1":
        return True
    status, body = api.get(PY_BASE, "/api/llm/models")
    if status != 200 or not isinstance(body, (list, dict)):
        return False
    if isinstance(body, dict):
        body = body.get("models") or body.get("items") or []
    return len(body) > 0


def fixture_path(name: str) -> Path:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"缺少夹具 {path} — 先运行 python3 tests/acceptance_metrics/prepare_fixtures.py")
    return path


# ---------------------------------------------------------------------------
# task lifecycle helpers
# ---------------------------------------------------------------------------

_task_cache: dict[tuple, dict] = {}


def run_analysis_task(api: Api, image_path: str | Path, *, scenarios=(),
                      llm_analyze=False, llm_event_analyze=False,
                      platform_analyze=True,
                      timeout: int = TASK_TIMEOUT,
                      extra: dict | None = None, cache_key: str | None = None) -> dict:
    """Create an analysis task and wait for a terminal status (cached).

    platform_analyze gates the windows/linux/android artifact analyzers
    (platform DBs); the lightweight-filtering metrics only need the
    ingest+classify+events pipeline, which those callers turn off.
    llm_event_analyze gates task-time event-cluster analysis — the seed
    source of the workbench event axis (M3-1).
    """
    key = (cache_key or str(image_path), tuple(sorted(scenarios)),
           llm_analyze, llm_event_analyze, platform_analyze)
    if key in _task_cache:
        return _task_cache[key]

    # 复用已完成的任务（如 TRACELENS_ACCEPT_LLM_TASK_ID），避免重复长分析。
    reuse_id = os.environ.get("TRACELENS_ACCEPT_LLM_TASK_ID", "")
    if cache_key == "raw-llm-acc" and reuse_id:
        status, task = api.get(CPP_BASE, f"/api/tasks/{reuse_id}")
        assert status == 200, f"复用任务 {reuse_id} 不存在({status})"
        assert str(task.get("status", "")).lower() == "completed", \
            f"复用任务 {reuse_id} 未完成: {task.get('status')}"
        _task_cache[key] = task
        return task

    body = {"image_path": str(image_path),
            "case_description": "第三方验收自动用例 " + TIMESTAMP,
            "scenarios": list(scenarios),
            "llm_analyze": llm_analyze,
            "llm_event_analyze": llm_event_analyze,
            "platform_analyze": platform_analyze}
    body.update(extra or {})
    status, task = api.post(CPP_BASE, "/api/tasks", json=body)
    assert status == 201, f"创建任务失败({status}): {task}"
    task_id = task["id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, task = api.get(CPP_BASE, f"/api/tasks/{task_id}")
        assert status == 200, f"查询任务失败({status})"
        if str(task.get("status", "")).lower() in ("completed", "failed", "cancelled"):
            break
        time.sleep(1.0)
    assert str(task.get("status", "")).lower() == "completed", \
        f"任务未在 {timeout}s 内完成: status={task.get('status')} id={task_id}"
    _task_cache[key] = task
    return task


def overview(api: Api, task_id: str) -> dict:
    """GET statistics/overview, normalized: each stats group unwrapped to one dict."""
    status, body = api.get(CPP_BASE, f"/api/forensics/statistics/overview?task_id={task_id}")
    assert status == 200, f"statistics/overview 失败({status})"
    for group in ("raw_database_stats", "files_database_stats", "events_database_stats"):
        if isinstance(body.get(group), list):
            body[group] = body[group][0] if body[group] else {}
    return body


def task_db(task_id: str, kind: str) -> Path:
    """Locate a task-owned SQLite file: {data_dir}/tasks/{task_id}/{kind}.db."""
    candidates = [DATA_DIR / "tasks" / task_id / f"{kind}.db",
                  ROOT / "build" / "data" / "tasks" / task_id / f"{kind}.db"]
    for path in candidates:
        if path.exists():
            return path
    pytest.skip(f"任务库不存在: {candidates[0]}（检查 TRACELENS_DATA_DIR，当前 {DATA_DIR}）")
    return candidates[0]


def db_scalar(db: Path, sql: str, params=()):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _audit_db() -> Path:
    for candidate in (DATA_DIR / "audit" / "forensics_audit.db",
                      ROOT / "build" / "data" / "audit" / "forensics_audit.db"):
        if candidate.exists():
            return candidate
    pytest.skip(f"审计库不存在（检查 TRACELENS_DATA_DIR，当前 {DATA_DIR}）")
    return candidate


def filtering_pipeline_seconds(task_id: str) -> float:
    """墙钟窗口 = 任务创建 → 过滤产物(files.db)首次落库（审计 RESULT_SET）。

    刻意排除其后的 Graphiti 知识图谱摄入（finalizing 阶段等待），那不是
    轻量化过滤流水线的一部分。
    """
    conn = sqlite3.connect(f"file:{_audit_db()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT event_type, timestamp_ms FROM audit_logs WHERE task_id = ? ORDER BY id",
            (task_id,)).fetchall()
    finally:
        conn.close()
    created = next((ts for evt, ts in rows if evt == "CREATED"), None)
    filtered = next((ts for evt, ts in rows if evt == "RESULT_SET"), None)
    if created is None or filtered is None:
        pytest.skip("审计库缺少 CREATED/RESULT_SET 记录，无法计算过滤窗口")
    return max((filtered - created) / 1000.0, 0.001)


def llm_analyze_content(api: Api, file_path: str, *, llm_ready: bool,
                        prompt: str | None = None) -> dict:
    """POST /api/llm/analyze — auto-routes text/vision/video by file type."""
    if not llm_ready:
        pytest.skip("LLM 未配置（/api/llm/models 为空）；配置后重跑，或设 TRACELENS_ACCEPT_ASSUME_LLM=1")
    payload = {"file_path": file_path}
    if prompt:
        payload["prompt"] = prompt
    status, body = api.post(PY_BASE, "/api/llm/analyze", json=payload)
    assert status == 200, f"/api/llm/analyze 失败({status}): {body}"
    return body
