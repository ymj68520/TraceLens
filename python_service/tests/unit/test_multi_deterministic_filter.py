"""Cross-image quotas retain distinct task/source identities."""
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from httpserver.services.case_analysis.multi_image_filter import MultiImageFilter

@pytest.mark.asyncio
async def test_same_name_size_path_keeps_other_image_source(tmp_path):
    databases=[]
    for i in range(2):
        path=str(tmp_path/f'{i}.db');databases.append(path)
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE files(path TEXT,type TEXT,size INTEGER)')
    refs=[f"source:v1:{str(i)*64}:/same/History" for i in (1,2)]
    selected=[{'task_id':task,'reference':reference} for task,reference in zip(['a','b'],refs)]
    backend=SimpleNamespace(selection_plan=AsyncMock(return_value={'schema_version':1,'plan_id':'p','selected':selected,'counts':{'indexed':2},'budget':{'files':2}}))
    service=MultiImageFilter(SimpleNamespace(file_filter_mode='deterministic',filter_max_files=10),None,backend)
    result=await service.filter_files_multi(databases,'',max_files=2,task_ids=['a','b'])
    assert result['selected_count']==2 and result['per_task']=={'a':[refs[0]],'b':[refs[1]]}
    backend.selection_plan.assert_awaited_once_with(['a','b'],2)
    for database,reference in zip(databases,refs):
        with sqlite3.connect(database) as db:assert reference in db.execute('SELECT filtered_files FROM case_analysis').fetchone()[0]

def test_legacy_helper_only_removes_same_source_reference():
    service=MultiImageFilter(SimpleNamespace(),None,None)
    rows=[{'task_id':'a','source_id':'1'*64,'path':'/History','size':4096},
          {'task_id':'b','source_id':'2'*64,'path':'/History','size':4096}]
    assert service._cross_image_dedup(rows+rows[:1])==rows

@pytest.mark.asyncio
async def test_global_cap_cannot_multiply_by_image_count():
    backend=SimpleNamespace(selection_plan=AsyncMock(return_value={'schema_version':1,'selected':[{'task_id':'a','reference':'1'},{'task_id':'b','reference':'2'}]}))
    service=MultiImageFilter(SimpleNamespace(filter_max_files=1),None,backend)
    with pytest.raises(ValueError,match='超出'):await service.filter_files_multi(['a.db','b.db'],'',max_files=100,task_ids=['a','b'])
    backend.selection_plan.assert_awaited_once_with(['a','b'],1)
