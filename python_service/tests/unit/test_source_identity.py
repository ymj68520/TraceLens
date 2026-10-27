import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
import pytest

from httpserver.services.source_identity import (canonical,locator_hash,file_row,evidence_key,
    analysis_reference,SourceIdentityError)
from httpserver.services.source_reading import resolve_source
from httpserver.services.evidence.keys import parse_evidence_key
from httpserver.services.investigation.models import FileSnapshotPayload
from httpserver.services.forensic_report.models import NeutralMaterial


def setup_sources(root, entries, indexed=True):
    root.mkdir(parents=True,exist_ok=True)
    dbpath=root/'files.db';extraction=root/'extracted_files';extraction.mkdir(exist_ok=True)
    revision=hashlib.sha256(str(root).encode()).hexdigest();ids=[];locators=[]
    with sqlite3.connect(dbpath) as db:
        db.executescript('''CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT,name TEXT,inode INTEGER,partition_num INTEGER,
          is_deleted INTEGER,size INTEGER,mtime INTEGER,ctime INTEGER,md5 TEXT,source_id TEXT,extension TEXT,category TEXT,type TEXT,
          llm_summary TEXT,llm_description TEXT,llm_keywords TEXT,llm_analyzed_at INTEGER,llm_model_used TEXT,
          scene_type TEXT,scene_priority INTEGER,scene_relevant INTEGER);
          CREATE TABLE source_index_meta(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE source_objects(source_id TEXT PRIMARY KEY,locator_json TEXT);''')
        db.execute('INSERT INTO source_index_meta VALUES(?,?)',('revision',revision))
        for i,(path,inode,deleted,data) in enumerate(entries,1):
            name=path.rsplit('/',1)[-1]
            locator={'version':1,'source_revision':revision,'source_kind':'physical','identity_scope':'acquisition_index',
                     'raw_record_id':i,'logical_path':path,'logical_name':name,'size':len(data),'mtime':100,'ctime':90,
                     'is_deleted':deleted,'partition_num':6,'inode':inode,'data_stream':'default','attribute_id':None}
            sid=locator_hash(locator) if indexed else None;ids.append(sid);locators.append(locator)
            db.execute('INSERT INTO files(id,path,name,inode,partition_num,is_deleted,size,mtime,ctime,md5,source_id,type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (i,path,name,inode,6,deleted,len(data),100,90,hashlib.md5(data).hexdigest(),sid,'REG'))
            if indexed:
                db.execute('INSERT INTO source_objects VALUES(?,?)',(sid,canonical(locator)))
                folder=extraction/'by-source'/sid;(folder/'payload').mkdir(parents=True)
                (folder/'payload'/name).write_bytes(data)
                (folder/'source.json').write_text(json.dumps({'schema_version':1,'payload_directory':'payload','source_id':sid,'locator':locator,
                    'components':[{'role':'primary','source_id':sid,'file_name':name,'logical_name':name,'size':len(data),
                                   'sha256':hashlib.sha256(data).hexdigest()}],'limitations':[]}),encoding='utf-8')
            else:
                target=extraction/path.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return {'id':'task','output_files_db':str(dbpath),'extraction_directory':str(extraction)},ids,locators


def test_same_path_live_deleted_and_snapshot_identity(tmp_path):
    task,ids,locators=setup_sources(tmp_path,[('/case/a.txt',89169,0,b'live'),('/case/a.txt',120441,1,b'deleted')])
    assert ids[0]!=ids[1]
    with sqlite3.connect(task['output_files_db']) as db:
        with pytest.raises(SourceIdentityError,match='SOURCE_PATH_AMBIGUOUS'):file_row(db,'/case/a.txt')
        assert file_row(db,'/case/a.txt',ids[0])[0]['inode']==89169
        assert file_row(db,'/case/a.txt',ids[1])[0]['inode']==120441
    for sid,data in zip(ids,[b'live',b'deleted']):
        key=evidence_key('/case/a.txt',sid);parsed=parse_evidence_key(key)
        assert parsed.normalized_path=='/case/a.txt' and parsed.source_id==sid
        bundle=resolve_source(task,'/case/a.txt',sid)
        with bundle.snapshot() as (path,hashes,provenance):
            assert path.name=='a.txt' and path.read_bytes()==data
            assert hashes['sha256']==hashlib.sha256(data).hexdigest()
            assert provenance['source_id']==sid


def test_tamper_missing_and_cross_task_never_choose_another_row(tmp_path):
    task,ids,_=setup_sources(tmp_path/'one',[('/a.txt',1,0,b'one')])
    other,_,_=setup_sources(tmp_path/'two',[('/a.txt',1,0,b'one')])
    with pytest.raises(SourceIdentityError,match='SOURCE_NOT_FOUND'):resolve_source(other,'/a.txt',ids[0])
    with sqlite3.connect(task['output_files_db']) as db:db.execute('UPDATE files SET size=99')
    with pytest.raises(SourceIdentityError,match='SOURCE_RECORD_CHANGED'):resolve_source(task,'/a.txt',ids[0])


def test_snapshot_checks_frozen_copy_hash(tmp_path):
    task,ids,_=setup_sources(tmp_path,[('/a.txt',1,0,b'one')])
    bundle=resolve_source(task,'/a.txt',ids[0]);bundle.path.write_bytes(b'two')
    with pytest.raises(SourceIdentityError,match='SOURCE_HASH_CHANGED'):
        with bundle.snapshot():pass


def test_old_snapshot_and_material_serialization_have_no_added_null_fields():
    legacy=FileSnapshotPayload(normalized_path='/a.txt').model_dump(mode='json')
    assert 'source_id' not in legacy and 'source_locator' not in legacy
    text='原始材料'
    value={'material_id':'m0001','evidence_key':'file:/a.txt','kind':'text','text':text,'media_base64':'',
           'source_sha256':'','content_sha256':hashlib.sha256(text.encode()).hexdigest(),'original_characters':4,
           'status':'ready','limitations':[]}
    assert NeutralMaterial.model_validate(value).model_dump(mode='json')==value


@pytest.mark.asyncio
async def test_analysis_write_updates_only_the_selected_source(tmp_path):
    from httpserver.services.llm.llm_service import LLMService
    task,ids,_=setup_sources(tmp_path,[('/a.txt',1,0,b'one'),('/a.txt',2,1,b'two')])
    service=object.__new__(LLMService)
    assert service.persist_to_files_db(task['output_files_db'],analysis_reference('/a.txt',ids[1]),'已删除记录说明','摘要','关键词',task_id='task')
    assert not service.persist_to_files_db(task['output_files_db'],'/a.txt','不应覆盖两个来源','摘要','',task_id='task')
    with sqlite3.connect(task['output_files_db']) as db:
        assert db.execute('SELECT llm_description FROM files WHERE inode=1').fetchone()[0] is None
        assert db.execute('SELECT llm_description FROM files WHERE inode=2').fetchone()[0]=='已删除记录说明'
        assert db.execute('SELECT source_id FROM file_analyses').fetchall()==[(ids[1],)]


@pytest.mark.asyncio
async def test_extensionless_sqlite_wal_is_read_from_isolated_snapshot(tmp_path):
    from httpserver.services.document_extractor import get_document_extractor_locator
    from httpserver.services.extractors.sqlite_records import SQLiteExtractor
    root=tmp_path/'evidence';root.mkdir()
    source=root/'History'
    writer=sqlite3.connect(source)
    writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
    writer.execute('CREATE TABLE visits(id INTEGER PRIMARY KEY,note TEXT)');writer.commit()
    writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    writer.execute("INSERT INTO visits VALUES(1,'只在 WAL 中的记录')");writer.commit()
    wal=Path(str(source)+'-wal')
    before=(hashlib.sha256(source.read_bytes()).hexdigest(),hashlib.sha256(wal.read_bytes()).hexdigest())
    try:
        extractor=get_document_extractor_locator().get_extractor(str(source))
        assert isinstance(extractor,SQLiteExtractor)
        result=await extractor.extract_result(str(source))
        assert '只在 WAL 中的记录' in result.text
        assert result.records[0]['locator']['primary_key']=={'id':1}
        assert result.coverage['source_snapshot']['wal']['committed_frames']>0
        assert before==(hashlib.sha256(source.read_bytes()).hexdigest(),hashlib.sha256(wal.read_bytes()).hexdigest())
    finally:writer.close()


@pytest.mark.asyncio
async def test_hive_magic_and_logical_name_use_registry_parser(tmp_path):
    from httpserver.services.document_extractor import get_document_extractor_locator
    from httpserver.services.extractors.windows_registry import RegistryExtractor
    path=tmp_path/'SOFTWARE';path.write_bytes(b'regf'+bytes(4092))
    assert isinstance(get_document_extractor_locator().get_extractor(str(path)),RegistryExtractor)


def test_platform_root_is_considered_even_when_main_root_exists(tmp_path):
    task,_,_=setup_sources(tmp_path,[('/etc/test.txt',1,0,b'data')],indexed=False)
    original=Path(task['extraction_directory'])/'etc/test.txt'
    other=tmp_path/'linux_extracted_files/etc/test.txt';other.parent.mkdir(parents=True)
    original.replace(other)
    assert resolve_source(task,'/etc/test.txt').path==other
