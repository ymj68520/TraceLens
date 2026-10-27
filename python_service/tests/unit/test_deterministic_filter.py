"""Automatic selection consumes a native plan, with one effective cap."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from httpserver.services.case_analysis.file_filter import FileFilter

def fixture(tmp_path,cap=0,mode='deterministic'):
    database=tmp_path/'files.db'
    with sqlite3.connect(database) as db:db.execute('CREATE TABLE files(path TEXT,type TEXT,size INTEGER)')
    async def plan(tasks,maximum):
        paths=['/z/important.txt','/a/background.txt','/b/config.xml']
        return {'schema_version':1,'plan_id':'p','selected':[{'task_id':tasks[0],'reference':p} for p in paths[:maximum or 3]],
                'counts':{'indexed':3,'selected':min(maximum or 3,3)},'budget':{'files':maximum or 500}}
    backend=SimpleNamespace(selection_plan=AsyncMock(side_effect=plan))
    service=FileFilter(SimpleNamespace(file_filter_mode=mode,filter_max_files=cap),None,backend)
    return service,str(database),backend

@pytest.mark.asyncio
async def test_native_order_is_kept_instead_of_resorting_paths(tmp_path):
    f,db,backend=fixture(tmp_path)
    result=await f.filter_files_by_case(db,'',max_files=2,task_id='t1')
    assert result['filtered_files']==['/z/important.txt','/a/background.txt']
    backend.selection_plan.assert_awaited_once_with(['t1'],2)
    assert result['model_used']=='native_selection'

@pytest.mark.asyncio
async def test_effective_cap_is_minimum_of_request_and_config(tmp_path):
    f,db,backend=fixture(tmp_path,cap=1)
    result=await f.filter_files_by_case(db,'',max_files=200,task_id='t1')
    assert result['selected_count']==1
    backend.selection_plan.assert_awaited_once_with(['t1'],1)

@pytest.mark.asyncio
async def test_missing_native_backend_does_not_fall_back_to_unlimited_paths(tmp_path):
    f,db,_=fixture(tmp_path);f._cpp_backend=None
    with pytest.raises(ValueError,match='原生后端'):await f.filter_files_by_case(db,'',max_files=2,task_id='t1')

@pytest.mark.asyncio
async def test_legacy_llm_setting_uses_same_budgeted_plan(tmp_path):
    f,db,backend=fixture(tmp_path,mode='llm')
    result=await f.filter_files_by_case(db,'',max_files=2,task_id='t1')
    assert result['selected_count']==2 and backend.selection_plan.await_count==1

@pytest.mark.asyncio
async def test_plan_exceeding_request_cap_is_rejected(tmp_path):
    f,db,backend=fixture(tmp_path);backend.selection_plan.side_effect=None
    backend.selection_plan.return_value={'schema_version':1,'selected':[{'task_id':'t1','reference':str(i)} for i in range(3)]}
    with pytest.raises(ValueError,match='超出'):await f.filter_files_by_case(db,'',max_files=2,task_id='t1')

@pytest.mark.asyncio
async def test_task_identity_comes_from_database_directory(tmp_path):
    parent=tmp_path/'tasks'/'task-a';parent.mkdir(parents=True)
    f,db,backend=fixture(parent)
    await f.filter_files_by_case(db,'',max_files=1)
    backend.selection_plan.assert_awaited_once_with(['task-a'],1)
    with sqlite3.connect(db) as conn:assert conn.execute('SELECT task_id FROM case_analysis').fetchone()[0]=='task-a'
