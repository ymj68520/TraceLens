"""Boundary regressions for identity propagation and isolated source reads."""
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_source_identity import setup_sources
from httpserver.services.source_identity import analysis_reference,SourceIdentityError,evidence_key
from httpserver.services.source_reading import resolve_source,task_source_file,source_reference_for_read


def test_escaped_source_name_keeps_raw_bytes_in_read_provenance(tmp_path):
    from httpserver.services.source_identity import locator_hash,canonical
    path='/case/__source_bytes_x8c031c__'
    task,ids,locators=setup_sources(tmp_path,[(path,71,0,b'original source bytes')])
    locator={**locators[0],'name_encoding':'lossless-component-bytes:v1',
             'raw_name_hex':'8c031c','raw_path_hex':b'/case/\x8c\x03\x1c'.hex()}
    identity=locator_hash(locator)
    with sqlite3.connect(task['output_files_db']) as db:
        db.execute('UPDATE files SET source_id=? WHERE source_id=?',(identity,ids[0]))
        db.execute('UPDATE source_objects SET source_id=?,locator_json=? WHERE source_id=?',(identity,canonical(locator),ids[0]))
    root=Path(task['extraction_directory'])/'by-source';(root/ids[0]).rename(root/identity)
    manifest_path=root/identity/'source.json';manifest=json.loads(manifest_path.read_text())
    manifest.update(source_id=identity,locator=locator);manifest['components'][0]['source_id']=identity
    manifest_path.write_text(json.dumps(manifest))
    bundle=resolve_source(task,path,identity)
    assert any('原始路径与名称字节' in note for note in bundle.limitations)
    with bundle.snapshot() as (copy,hashes,provenance):
        assert copy.read_bytes()==b'original source bytes'
        assert provenance['locator']['raw_name_hex']=='8c031c'
        assert provenance['source_id']==identity


@pytest.mark.parametrize('name',['source.json','source-1.tmp','History','SOFTWARE','中文 记录.txt'])
def test_logical_name_does_not_collide_with_manifest(tmp_path,name):
    task,ids,_=setup_sources(tmp_path,[('/case/'+name,1,0,b'original')])
    bundle=resolve_source(task,'/case/'+name,ids[0])
    with bundle.snapshot() as (copy,hashes,provenance):
        assert copy.name==name and copy.read_bytes()==b'original'
        assert source_reference_for_read(str(copy))==analysis_reference('/case/'+name,ids[0])
    assert not copy.exists()
    assert json.loads((bundle.path.parent.parent/'source.json').read_text())['source_id']==ids[0]


def test_analysis_accessors_and_timeline_do_not_merge_sources(tmp_path):
    from httpserver.services.llm.llm_service import LLMService
    from httpserver.services.case_analysis.file_schema import latest_analysis,latest_analyses_batch,list_analyses,analysis_stats
    from httpserver.services.investigation.file_timeline import collect_file_timeline
    task,ids,_=setup_sources(tmp_path,[('/a.txt',1,0,b'one'),('/a.txt',2,1,b'two')])
    service=object.__new__(LLMService)
    refs=[analysis_reference('/a.txt',sid) for sid in ids]
    for index,ref in enumerate(refs):
        assert service.persist_to_files_db(task['output_files_db'],ref,f'来源{index}','摘要','',task_id='task')
        assert latest_analysis(task['output_files_db'],ref)['description']==f'来源{index}'
        assert len(list_analyses(task['output_files_db'],'task',ref))==1
    assert len(latest_analyses_batch(task['output_files_db'],refs))==2
    assert analysis_stats(task['output_files_db'])==dict(total=2,analyzed=2,pending=0,stale=0)
    with pytest.raises(SourceIdentityError,match='AMBIGUOUS'):
        latest_analysis(task['output_files_db'],'/a.txt')
    result=collect_file_timeline(tmp_path/'absent.db','task',task)
    assert result['total_count']==2
    assert {r['source_id'] for r in result['files']}==set(ids)
    assert {r['evidence_key'] for r in result['files']}=={evidence_key('/a.txt',sid) for sid in ids}


@pytest.mark.asyncio
async def test_host_absolute_file_cannot_replace_task_source(tmp_path):
    task,ids,_=setup_sources(tmp_path/'task',[('/same.txt',1,0,b'evidence')])
    host=tmp_path/'same.txt';host.write_bytes(b'host-data')
    with pytest.raises(SourceIdentityError,match='SOURCE_NOT_FOUND'):
        async with task_source_file('task',str(host),task=task):pass
    bundle=resolve_source(task,'/same.txt',ids[0])
    async with task_source_file('task',str(bundle.path),task=task) as (copy,reference,_):
        assert Path(copy).read_bytes()==b'evidence'
        assert reference==analysis_reference('/same.txt',ids[0])


def test_legacy_frozen_size_is_checked_even_if_schema_lacks_size(tmp_path):
    task,_,_=setup_sources(tmp_path,[('/a.txt',1,0,b'one')],indexed=False)
    with sqlite3.connect(task['output_files_db']) as db:db.execute('ALTER TABLE files DROP COLUMN size')
    bundle=resolve_source(task,'/a.txt',expected=SimpleNamespace(size=4))
    with pytest.raises(SourceIdentityError,match='SOURCE_SIZE_CHANGED'):
        with bundle.snapshot():pass


@pytest.mark.asyncio
async def test_corrupt_wal_cannot_silently_read_main_database(tmp_path):
    from httpserver.services.extractors.sqlite_records import SQLiteExtractor
    from httpserver.services.extractors.base import DocumentContentUnavailableError
    source=tmp_path/'History';writer=sqlite3.connect(source)
    writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
    writer.execute('CREATE TABLE entries(note TEXT)');writer.commit()
    main=source.read_bytes();wal=Path(str(source)+'-wal').read_bytes()
    isolated=tmp_path/'broken';isolated.mkdir();target=isolated/'History'
    target.write_bytes(main);Path(str(target)+'-wal').write_bytes(wal[:-1])
    try:
        with pytest.raises(DocumentContentUnavailableError,match='WAL'):
            await SQLiteExtractor().extract_result(str(target))
        assert target.read_bytes()==main and Path(str(target)+'-wal').read_bytes()==wal[:-1]
    finally:writer.close()


@pytest.mark.asyncio
async def test_interactive_analyze_reads_selected_source_and_rejects_ambiguity(tmp_path,monkeypatch):
    from httpserver.routes.llm_endpoints._analysis import analyze_content
    from httpserver.routes.llm_models import AnalyzeRequest
    import httpserver.services as services
    from httpserver.services import task_store
    from fastapi import HTTPException
    task,ids,_=setup_sources(tmp_path,[('/a.txt',1,0,'现存正文'.encode()),('/a.txt',2,1,'删除正文'.encode())])
    llm=SimpleNamespace(analyze=AsyncMock(return_value={'analysis':{'description':'分析结论'},'model':'test'}),persist_to_files_db=lambda **kwargs:True)
    manager=SimpleNamespace(cpp_backend=SimpleNamespace(get_task=AsyncMock(return_value=task)),llm_service=llm)
    monkeypatch.setattr(services,'get_service_manager',lambda:manager)
    monkeypatch.setattr(task_store,'resolve_task_files_db',AsyncMock(return_value=Path(task['output_files_db'])))
    result=await analyze_content(AnalyzeRequest(task_id='task',file_path='/a.txt',source_id=ids[1]),SimpleNamespace())
    assert result.success
    assert llm.analyze.call_args.kwargs['content']=='删除正文'
    with pytest.raises(HTTPException) as error:
        await analyze_content(AnalyzeRequest(task_id='task',file_path='/a.txt'),SimpleNamespace())
    assert error.value.status_code==409 and llm.analyze.await_count==1


@pytest.mark.asyncio
async def test_existing_extraction_phase_uses_exact_identity_instead_of_glob(tmp_path):
    from httpserver.services.case_analysis.case_analysis_parts._windows import CaseAnalysisWindowsMixin
    service=object.__new__(CaseAnalysisWindowsMixin)
    backend=SimpleNamespace(get_task=AsyncMock(return_value={'extraction_directory':str(tmp_path)}),
        materialize_source=AsyncMock(return_value={'success':True}),extract_files=AsyncMock())
    service._cpp_backend=backend
    sid='a'*64
    result=await service.extract_filtered_files('task',[analysis_reference('/含逗号,的文件.txt',sid)])
    assert result['extracted_count']==1
    backend.materialize_source.assert_awaited_once_with('task','/含逗号,的文件.txt',sid)
    backend.extract_files.assert_not_called()
