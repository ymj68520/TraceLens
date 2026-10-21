import sqlite3
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import BaseModel

from httpserver.services.investigation.agent_tools.adapters.cross_image import (
    build_search_shared_indicators_tool,
    build_correlate_timeline_tool,
    SearchSharedIndicatorsInput,
    CorrelateTimelineInput,
)
from httpserver.services.investigation.agent_tools.adapters.services import ForensicToolServices
from httpserver.services.investigation.agent_tools.adapters.base import ToolCatalogConfig


@pytest.fixture
def mock_dbs(tmp_path):
    pc_dir = tmp_path / "pc"
    pc_dir.mkdir()
    server_dir = tmp_path / "server"
    server_dir.mkdir()

    pc_files = pc_dir / "files.db"
    pc_events = pc_dir / "events.db"
    server_files = server_dir / "files.db"
    server_events = server_dir / "events.db"

    # Setup PC files.db
    conn = sqlite3.connect(pc_files)
    conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY, name TEXT, path TEXT, md5 TEXT)")
    conn.execute("INSERT INTO files VALUES (1, 'malware.exe', 'C:\\Users\\Admin\\malware.exe', 'e99a18c428cb38d5f260853678922e03')")
    conn.execute("INSERT INTO files VALUES (2, 'notes.txt', 'C:\\Users\\Admin\\notes.txt', '11111111111111111111111111111111')")
    conn.commit()
    conn.close()

    # Setup PC events.db
    conn = sqlite3.connect(pc_events)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT)")
    conn.execute("INSERT INTO events VALUES (1, 1700000000, 'PROCESS_START', 'malware.exe executed')")
    conn.commit()
    conn.close()

    # Setup Server files.db (shares malware md5)
    conn = sqlite3.connect(server_files)
    conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY, name TEXT, path TEXT, md5 TEXT)")
    conn.execute("INSERT INTO files VALUES (1, 'backdoor.bin', '/tmp/backdoor.bin', 'e99a18c428cb38d5f260853678922e03')")
    conn.commit()
    conn.close()

    # Setup Server events.db (aligned around 1700000000)
    conn = sqlite3.connect(server_events)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT)")
    conn.execute("INSERT INTO events VALUES (1, 1700000005, 'SSH_LOGIN', 'Login from suspect IP')")
    conn.commit()
    conn.close()

    return {
        "pc_files": str(pc_files),
        "pc_events": str(pc_events),
        "server_files": str(server_files),
        "server_events": str(server_events),
    }


@pytest.fixture
def mock_services(mock_dbs):
    cpp_mock = MagicMock()
    cpp_mock.list_cases = AsyncMock(return_value={
        "cases": [
            {
                "id": "case_test_01",
                "task_ids": ["task_pc", "task_server"],
            }
        ]
    })
    
    async def get_task_mock(task_id):
        if task_id == "task_pc":
            return {
                "id": "task_pc",
                "image_name": "窝点嫌疑人计算机镜像.E01",
                "output_files_db": mock_dbs["pc_files"],
                "output_events_db": mock_dbs["pc_events"],
            }
        elif task_id == "task_server":
            return {
                "id": "task_server",
                "image_name": "服务器镜像.E01",
                "output_files_db": mock_dbs["server_files"],
                "output_events_db": mock_dbs["server_events"],
            }
        return None

    cpp_mock.get_task = AsyncMock(side_effect=get_task_mock)
    services = MagicMock(spec=ForensicToolServices)
    services.cpp_backend = cpp_mock
    return services


@pytest.mark.asyncio
async def test_search_shared_indicators(mock_services):
    config = MagicMock(spec=ToolCatalogConfig)
    definition, adapter = build_search_shared_indicators_tool(mock_services, config)

    invocation = MagicMock()
    invocation.context.task_id = "task_pc"
    invocation.args = SearchSharedIndicatorsInput(indicator_type="hash", min_occurrences=2)

    outcome = await adapter(invocation)
    assert outcome is not None
    assert outcome.result.total_shared >= 1
    assert any("e99a18c428cb38d5f260853678922e03" in item.indicator_value for item in outcome.result.shared_indicators)
    # Check that FQER evidence refs contain both scopes
    scopes_in_evidence = {ref.split(":")[0] for ref in outcome.evidence_refs}
    assert "src_pc" in scopes_in_evidence
    assert "src_server" in scopes_in_evidence


@pytest.mark.asyncio
async def test_correlate_timeline(mock_services):
    config = MagicMock(spec=ToolCatalogConfig)
    definition, adapter = build_correlate_timeline_tool(mock_services, config)

    invocation = MagicMock()
    invocation.context.task_id = "task_pc"
    invocation.args = CorrelateTimelineInput(
        start_unix=1699999000,
        end_unix=1700001000,
        tolerance_seconds=60,
    )

    outcome = await adapter(invocation)
    assert outcome is not None
    assert outcome.result.total_clusters >= 1
    cluster = outcome.result.correlated_clusters[0]
    assert "src_pc" in cluster.scopes_involved
    assert "src_server" in cluster.scopes_involved
    assert any("src_pc:cluster:v1:" in k for k in cluster.evidence_keys)
    assert any("src_server:cluster:v1:" in k for k in cluster.evidence_keys)
