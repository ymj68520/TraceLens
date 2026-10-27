import hashlib,json,sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from httpserver.services.evidence.keys import parse_evidence_key
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.evidence.exceptions import EvidenceNotFoundError,EvidenceStoreError
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.windows_activity_reader import detail,key

def fixture(tmp_path):
    events=tmp_path/'events.db';files=tmp_path/'files.db';result='a'*64
    record={'source_table':'event_logs','source_row_id':1,'fields':{'source':'测试提供程序','event_id':1,'message':'实际记录内容'},
            'parser_status':'ok','source':{'path':'/Windows/System32/winevt/Logs/test.evtx','source_id':None,'binding_status':'unresolved'},
            'event_type':'WINDOWS_EVENT_RECORD','observation':'Windows事件日志记录','time_basis':'event_system_time',
            'timestamp_timezone':'UTC','timestamp_precision':'seconds','times':[{'timestamp':1700000000,'raw_time':'2023-11-14T22:13:20Z','slot':'timestamp'}],
            'is_recovered':False}
    raw=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(raw.encode()).hexdigest()
    with sqlite3.connect(events) as conn:
        conn.executescript('CREATE TABLE windows_activity_records(record_id INTEGER PRIMARY KEY,result_set_id TEXT,source_table TEXT,source_row_id INTEGER,record_hash TEXT,record_json TEXT);'
            'CREATE TABLE windows_activity_sets(result_set_id TEXT PRIMARY KEY,task_id TEXT,source_revision TEXT,import_version TEXT,coverage_json TEXT);'
            'CREATE TABLE windows_activity_current(task_id TEXT PRIMARY KEY,result_set_id TEXT);')
        conn.execute('INSERT INTO windows_activity_records VALUES(?,?,?,?,?,?)',(1,result,'event_logs',1,digest,raw))
        conn.execute('INSERT INTO windows_activity_sets VALUES(?,?,?,?,?)',(result,'task','b'*64,'windows-activity:v1',json.dumps({'tables':{'event_logs':{'input':1,'valid':1}}})))
        conn.execute('INSERT INTO windows_activity_current VALUES(?,?)',('task',result))
    with sqlite3.connect(files) as conn:
        conn.execute('CREATE TABLE files(path TEXT,source_id TEXT,llm_analyzed_at INTEGER)')
    task={'id':'task','output_events_db':str(events),'output_files_db':str(files)}
    backend=SimpleNamespace(get_task=AsyncMock(return_value=task))
    return task,backend,key('task',result,'event_logs',1),digest

@pytest.mark.asyncio
async def test_windows_record_identity_freezes_into_existing_report_flow(tmp_path):
    from httpserver.services.forensic_report.generation import ReportGenerationInputBuilder
    from httpserver.services.forensic_report.generation_sources import freeze_materials,sanitize_items
    from httpserver.services.forensic_report.models import ReportGenerationEnvelopeV7,ReportGenerationEnvelopeV6,material_scope_hash,parse_generation_envelope
    task,backend,reference,digest=fixture(tmp_path)
    resolved=await EvidenceResolver(backend).resolve_evidence('task',reference)
    repository=InvestigationRepository(tmp_path/'investigation.db','task')
    snapshot=repository.capture_if_absent(resolved)
    assert snapshot.payload.record_hash==digest and snapshot.payload.record_fields['fields']['message']=='实际记录内容'
    with sqlite3.connect(repository.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==9
        # Existing report binding schema is exercised through the public service below.
    from httpserver.services.investigation.report_evidence import ReportEvidenceService
    service=ReportEvidenceService(backend)
    service._resolve_task_db=AsyncMock(return_value=repository.db_path)
    await service.add('task',reference,report_status='main',added_by='test')
    scope=ReportGenerationInputBuilder(repository.db_path,'task').assemble('final-report:v4',case_description='')
    items=sanitize_items(scope.main_evidence);materials=await freeze_materials(task,items)
    assert materials[0].kind=='windows_record' and materials[0].source_sha256==digest
    assert '实际记录内容' in materials[0].text
    values=dict(task_id='task',prompt_version='final-report:evidence-only:v2',analysis_mode='evidence_only',case_description='',
        main_evidence=items,allowed_report_evidence_ids=(reference,),neutral_materials=materials,evidence_scope_hash=material_scope_hash(materials))
    envelope=ReportGenerationEnvelopeV7(**values)
    assert parse_generation_envelope(envelope.model_dump_json())==envelope
    with pytest.raises(ValueError,match='v7'):ReportGenerationEnvelopeV6(**values)
    # Updating the active pointer cannot redirect a frozen source reference.
    with sqlite3.connect(task['output_events_db']) as conn:conn.execute("UPDATE windows_activity_current SET result_set_id=?",('c'*64,))
    assert repository.get_snapshot(reference).payload==snapshot.payload

@pytest.mark.asyncio
@pytest.mark.parametrize('report_status', ['main', 'appendix'])
async def test_mixed_windows_and_file_scope_preserves_file_snapshot(tmp_path, report_status):
    from httpserver.services.evidence import ResolvedEvidence
    from httpserver.services.forensic_report.generation import ReportGenerationInputBuilder
    from httpserver.services.investigation.report_evidence import ReportEvidenceService
    task, backend, reference, _ = fixture(tmp_path)
    repository = InvestigationRepository(tmp_path/'investigation.db', 'task')
    repository.capture_if_absent(await EvidenceResolver(backend).resolve_evidence('task', reference))
    file_key = 'file:/note.txt'
    with sqlite3.connect(task['output_files_db']) as conn:
        for column in ('name extension category type size mtime ctime is_deleted md5 llm_summary '
                       'llm_description llm_keywords llm_model_used scene_type scene_priority scene_relevant').split():
            conn.execute(f'ALTER TABLE files ADD COLUMN {column}')
        conn.execute('INSERT INTO files(path,source_id,llm_analyzed_at) VALUES(?,NULL,NULL)', ('/note.txt',))
    file_snapshot = repository.capture_if_absent(ResolvedEvidence(
        task_id='task', evidence_key=file_key, evidence_type='file',
        normalized_path='/note.txt', source_db=task['output_files_db']))
    service = ReportEvidenceService(backend)
    service._resolve_task_db = AsyncMock(return_value=repository.db_path)
    await service.add('task', reference, report_status='main', added_by='test')
    await service.add('task', file_key, report_status=report_status, added_by='test')
    scope = ReportGenerationInputBuilder(repository.db_path, 'task').assemble('final-report:v4')
    assert len(scope.main_evidence)+len(scope.appendix_evidence) == 2
    item = next(i for i in (*scope.main_evidence, *scope.appendix_evidence) if i.evidence_key == file_key)
    assert item.snapshot.evidence_type == 'file'
    assert item.snapshot.payload == file_snapshot.payload
    assert repository.get_snapshot(file_key) == file_snapshot
    assert scope.allowed_report_evidence_ids == tuple(sorted((file_key, reference)))


@pytest.mark.asyncio
async def test_windows_keys_reject_other_task_and_tampered_record(tmp_path):
    task,backend,reference,_=fixture(tmp_path)
    with pytest.raises(EvidenceNotFoundError):await EvidenceResolver(backend).resolve_evidence('other',reference)
    with sqlite3.connect(task['output_events_db']) as conn:conn.execute("UPDATE windows_activity_records SET record_json='{}'")
    with pytest.raises(EvidenceStoreError,match='摘要'):await EvidenceResolver(backend).resolve_evidence('task',reference)
    for invalid in (reference.replace(':1',':0'),reference.replace('event_logs','unknown'),reference.replace('a'*64,'not-a-hash')):
        with pytest.raises(ValueError):parse_evidence_key(invalid)

def test_v8_migration_preserves_snapshot_bytes_constraints_and_foreign_keys(tmp_path):
    path=tmp_path/'investigation.db';old=InvestigationRepository.__new__(InvestigationRepository)
    old.db_path=path;old.task_id='task';old.existing_only=False;old._initialize_v8_atomically()
    original='{"evidence_type":"file","normalized_path":"/A.txt"}'
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES('task','file:/A.txt','file','/A.txt',?,1)",(original,))
    repo=InvestigationRepository(path,'task')
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==9
        assert conn.execute('SELECT snapshot_json FROM evidence_snapshots').fetchone()==(original,)
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        with pytest.raises(sqlite3.IntegrityError):conn.execute("UPDATE evidence_snapshots SET snapshot_json='{}'")
    assert repo.get_snapshot('file:/A.txt').payload.normalized_path=='/A.txt'
    assert path.with_name(path.name+'.before-v9.sqlite').is_file()

def test_archived_windows_result_remains_readable_after_timeline_rebuild(tmp_path):
    import shutil
    task,_,reference,digest=fixture(tmp_path)
    archive=tmp_path/'windows_history';archive.mkdir()
    shutil.copyfile(task['output_events_db'],archive/'historical.db')
    with sqlite3.connect(task['output_events_db']) as conn:
        conn.execute('DROP TABLE windows_activity_records');conn.execute('DROP TABLE windows_activity_sets')
    from httpserver.services.windows_activity_reader import parse_key
    owner,result,kind,record_id=parse_key(reference)
    assert detail(task['output_events_db'],owner,result,kind,record_id)['record_hash']==digest

@pytest.mark.asyncio
async def test_windows_source_seeding_is_bounded_and_preserves_exclusion(tmp_path):
    from httpserver.services.investigation.report_evidence import ReportEvidenceService
    from httpserver.services.investigation.paths import investigation_db_path_for_task
    task,backend,reference,_=fixture(tmp_path)
    repository=InvestigationRepository(investigation_db_path_for_task(task),'task')
    service=ReportEvidenceService(backend)
    assert await service._seed_windows_activity(task,added_by='test')==1
    assert await service._seed_windows_activity(task,added_by='test')==0
    await service.update('task',reference,report_status='excluded',updated_by='test')
    assert await service._seed_windows_activity(task,added_by='test')==0
    assert (await service.list('task'))[0].report_status.value=='excluded'

@pytest.mark.asyncio
@pytest.mark.parametrize('manually_kept',[False,True,'during_seed'])
async def test_new_result_supersedes_only_untouched_automatic_report_scope(tmp_path,manually_kept):
    from httpserver.services.investigation.report_evidence import ReportEvidenceService
    from httpserver.services.investigation.paths import investigation_db_path_for_task
    task,backend,old_key,_=fixture(tmp_path);service=ReportEvidenceService(backend)
    assert await service._seed_windows_activity(task,added_by='test')==1
    repo=InvestigationRepository(investigation_db_path_for_task(task),'task');old=repo.get_snapshot(old_key)
    if manually_kept is True:await service.update('task',old_key,report_status='main',updated_by='分析员')
    with sqlite3.connect(task['output_events_db']) as conn:
        conn.execute("INSERT INTO windows_activity_sets SELECT ?,task_id,source_revision,import_version,coverage_json FROM windows_activity_sets LIMIT 1",('c'*64,))
        conn.execute("INSERT INTO windows_activity_records SELECT 2,?,source_table,source_row_id,record_hash,record_json FROM windows_activity_records LIMIT 1",('c'*64,))
        conn.execute('UPDATE windows_activity_current SET result_set_id=?',('c'*64,))
    if manually_kept=='during_seed':
        original_list=service.list
        async def concurrent_judgment(task_id):
            old_projection=await original_list(task_id)
            await service.update(task_id,old_key,report_status='main',updated_by='分析员')
            return old_projection
        service.list=concurrent_judgment
    assert await service._seed_windows_activity(task,added_by='test')==1
    statuses={item.evidence_key:item.report_status.value for item in await service.list('task')}
    assert statuses[old_key]==('main' if manually_kept else 'excluded')
    assert repo.get_snapshot(old_key)==old
