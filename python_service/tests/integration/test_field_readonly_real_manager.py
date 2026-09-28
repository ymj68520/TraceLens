"""Actual manager initialization in disabled release mode; no executor mock."""
import hashlib,json,secrets,sqlite3
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpserver.config import Settings
from httpserver.services.service_manager import ServiceManager
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.routes import investigation_workbench, investigation

@pytest.mark.asyncio
async def test_disabled_release_manager_reads_v7_without_optional_executor(tmp_path,monkeypatch):
    files=tmp_path/'files.db'
    with sqlite3.connect(files) as con:
        con.execute('CREATE TABLE files(path TEXT)')
        con.execute("INSERT INTO files VALUES('/synthetic-old.txt')")
    db=tmp_path/'investigation.db'
    repo=InvestigationRepository.__new__(InvestigationRepository)
    repo.db_path,repo.task_id,repo.existing_only=db,'synthetic-readonly',False
    repo._initialize_v7_atomically()
    with sqlite3.connect(db) as con:
        con.execute('INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)',
            ('synthetic-readonly','file:/synthetic-old.txt','file','/synthetic-old.txt',
             '{"evidence_type":"file","normalized_path":"/synthetic-old.txt","initial_description":"SYNTHETIC_INITIAL"}',1))
    original=hashlib.sha256(db.read_bytes()).hexdigest()
    reports=tmp_path/'reports'; reports.mkdir(); ReportRepository(reports/'reports.db')
    users=tmp_path/'users.json'; users.write_text('{"users":{}}'); users.chmod(0o600)
    for key,value in {'TRACELENS_FIELD_AUTH':'enabled','TRACELENS_REQUIRE_FIELD_AUTH':'1',
                      'TRACELENS_REQUIRE_RELEASE_LAYOUT':'1','FIELD_OUTBOUND_POLICY':'disabled',
                      'FIELD_USER_FILE':str(users),'FIELD_JWT_SECRET':secrets.token_urlsafe(64),
                      'FIELD_CPP_TO_PYTHON_TOKEN':secrets.token_urlsafe(64),
                      'FIELD_PYTHON_TO_CPP_TOKEN':secrets.token_urlsafe(64),'FIELD_BROWSER_ORIGIN':''}.items():
        monkeypatch.setenv(key,value)
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.delenv(key,raising=False)
    task={'id':'synthetic-readonly','output_files_db':str(files)}
    class Cpp:
        def __init__(self,settings): pass
        async def initialize(self): pass
        async def shutdown(self): pass
        async def get_task(self,task_id): return task if task_id==task['id'] else None
    from httpserver.services import cpp_backend
    monkeypatch.setattr(cpp_backend,'CppBackendService',Cpp)
    manager=ServiceManager(Settings(project_root=str(tmp_path),report_output_dir=str(reports)))
    await manager.initialize()
    try:
        assert manager._secondary_analysis_executor is None
        assert manager._event_refresh_executor is None
        assert manager._report_generation_executor is None
        with pytest.raises(RuntimeError,match='executor is unavailable'):
            _=manager.secondary_analysis_executor
        app=FastAPI()
        app.include_router(investigation_workbench.router,prefix='/api/investigation/workbench')
        app.include_router(investigation.router,prefix='/api/investigation')
        app.dependency_overrides[investigation_workbench._manager]=lambda:manager
        app.dependency_overrides[investigation.get_investigation_read_service]=lambda:manager.investigation_read_service
        client=TestClient(app)
        base='/api/investigation/workbench/synthetic-readonly'
        overview=client.get(base)
        assert overview.status_code==200,overview.text
        assert overview.json()['read_only'] and overview.json()['store_schema_version']==7
        assert overview.json()['analyses']==[]
        params={'evidence_key':'file:/synthetic-old.txt'}
        assert client.get(base+'/evidence/analysis',params=params).json()['versions']==[]
        detail=client.get(base+'/evidence/detail',params=params)
        assert detail.status_code==200,detail.text
        assert detail.json()['evidence']['snapshot']['payload']['initial_description']=='SYNTHETIC_INITIAL'
        assert client.get(base+'/analysis-jobs/nonexistent').status_code==404
        assert client.get('/api/investigation/analyses',params={'task_id':task['id'],**params}).status_code==200
        assert client.get('/api/investigation/analyses/nonexistent',params={'task_id':task['id']}).status_code==404
        assert hashlib.sha256(db.read_bytes()).hexdigest()==original
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as con:
            assert con.execute('PRAGMA user_version').fetchone()[0]==7
    finally:
        await manager.shutdown()
