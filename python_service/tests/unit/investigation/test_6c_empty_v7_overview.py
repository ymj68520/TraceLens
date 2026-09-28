import hashlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from httpserver.routes.investigation_workbench import _overview

@pytest.mark.asyncio
async def test_empty_v7_overview_declares_readonly_without_writes(tmp_path):
    db = tmp_path / 'investigation.db'
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA user_version=7')
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    task = {'id':'synthetic-v7','output_files_db':str(tmp_path/'files.db')}
    manager = SimpleNamespace(
        cpp_backend=SimpleNamespace(get_task=AsyncMock(return_value=task)),
        investigation_read_service=SimpleNamespace(list_evidence=AsyncMock(return_value=[]),list_all_analyses=AsyncMock(return_value={})),
        investigation_event_service=SimpleNamespace(list_events=AsyncMock(return_value=[]),event_time_bounds=AsyncMock(return_value={})),
        report_evidence_service=SimpleNamespace(list=AsyncMock(return_value=[])),
        investigation_graph_service=SimpleNamespace(get_graph=AsyncMock(return_value={})),
        secondary_analysis_executor=SimpleNamespace(list_all_analyses=AsyncMock(return_value={})))
    result = await _overview('synthetic-v7',manager)
    assert result['read_only'] and result['store_schema_version']==7
    assert not result['initialized']
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before
