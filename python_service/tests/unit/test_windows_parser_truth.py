import asyncio
import os
import struct
import time
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from httpserver.services.extractors.base import BaseExtractor, DocumentContentUnavailableError
from httpserver.services.extractors.windows_prefetch import PrefetchExtractor
from httpserver.services.extractors.windows_evtx import EvtxExtractor, LEVEL_NAMES
from httpserver.services.extractors.windows_time import filetime_to_datetime

FIXTURES = Path(__file__).resolve().parents[3] / 'tests/fixtures/windows_parser_truth'


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['synthetic_v17.pf', 'synthetic_v17_mam.pf'])
async def test_real_libscca_decodes_known_plain_and_compressed(name):
    import pyscca  # Required for this acceptance test; absence must not silently skip it.
    result = await PrefetchExtractor().extract_result(str(FIXTURES/name))
    assert result.status == 'ok', result.diagnostics
    record = result.records[0]
    assert record['run_count'] == 2
    assert record['executable_name'] == 'SAMPLE.EXE'
    assert record['execution_times'] == [{'slot': 0, 'filetime': 133922046640650370, 'utc': '2025-05-20T08:51:04.065037Z'}]
    assert 'System32' not in result.text


@pytest.mark.asyncio
async def test_zero_run_count_and_missing_times_are_not_replaced(tmp_path):
    raw=bytearray((FIXTURES/'synthetic_v17.pf').read_bytes())
    struct.pack_into('<Q',raw,120,0); struct.pack_into('<I',raw,144,0)
    path=tmp_path/'zero.pf';path.write_bytes(raw)
    result=await PrefetchExtractor().extract_result(str(path))
    assert result.records[0]['run_count']==0
    assert result.records[0]['execution_times']==[]


@pytest.mark.asyncio
async def test_missing_latest_slot_is_partial_not_an_older_latest_time(tmp_path):
    raw=bytearray((FIXTURES/'synthetic_v17.pf').read_bytes())
    raw[84:304]=bytes(220)
    struct.pack_into('<I',raw,0,26)
    struct.pack_into('<Q',raw,136,133922046640650370)
    struct.pack_into('<I',raw,208,5)
    path=tmp_path/'missing-latest.pf';path.write_bytes(raw)
    result=await PrefetchExtractor().extract_result(str(path))
    assert result.status=='partial'
    assert 'PREFETCH_LATEST_TIME_UNAVAILABLE' in result.diagnostics
    assert [t['slot'] for t in result.records[0]['execution_times']]==[1]


@pytest.mark.parametrize('tz', ['UTC', 'Asia/Shanghai', 'America/New_York'])
def test_filetime_is_utc_and_retains_microseconds(tz):
    original=os.environ.get('TZ')
    try:
        os.environ['TZ']=tz
        if hasattr(time,'tzset'):time.tzset()
        value=filetime_to_datetime(133922046640650370)
        assert value.isoformat()=='2025-05-20T08:51:04.065037+00:00'
        assert value.tzinfo==timezone.utc
        assert filetime_to_datetime(0) is None
        assert filetime_to_datetime(2**64-1) is None
        assert filetime_to_datetime(116444735990000000).timestamp()==-1
    finally:
        if original is None:os.environ.pop('TZ',None)
        else:os.environ['TZ']=original
        if hasattr(time,'tzset'):time.tzset()


@pytest.mark.asyncio
async def test_failed_prefetch_has_no_execution_claim_or_diagnostic_body(tmp_path):
    path=tmp_path/'CLAIMED.EXE-12345678.pf';path.write_bytes(b'MAM\x04'+struct.pack('<I',4096)+bytes(32))
    result=await PrefetchExtractor().extract_result(str(path))
    assert result.status=='error'
    assert result.records==() and result.text==''
    with pytest.raises(DocumentContentUnavailableError):
        await PrefetchExtractor().extract_to_markdown_detailed(str(path))


@pytest.mark.asyncio
async def test_missing_libscca_is_unsupported(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules,'pyscca',None)
    result=await PrefetchExtractor().extract_result(str(FIXTURES/'synthetic_v17.pf'))
    assert result.status=='unsupported' and result.text=='' and not result.records


def event_xml(provider='Microsoft-Windows-Audio', event_id=22, level=4, stamp='2025-05-20T09:00:00Z', rid=1):
    return f'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
    <Provider Name="{provider}"/><EventID>{event_id}</EventID><Level>{level}</Level>
    <TimeCreated SystemTime="{stamp}"/><EventRecordID>{rid}</EventRecordID><Channel>Test</Channel></System>
    <EventData><Data Name="Value">sample</Data></EventData></Event>'''


def mock_log(monkeypatch, tmp_path, xmls, *, minor=2, checksum=True, broken_iteration=False):
    from Evtx import Evtx as module
    log=MagicMock();log.__enter__.return_value=log
    header=log.get_file_header.return_value
    header.magic.return_value='ElfFile\0';header.major_version.return_value=3
    header.minor_version.return_value=minor;header.header_chunk_size.return_value=4096
    header.chunk_count.return_value=0
    header.checksum.return_value=1;header.calculate_checksum.return_value=1 if checksum else 2
    records=[]
    for i,xml in enumerate(xmls):
        record=MagicMock();record.xml.return_value=xml;record.offset.return_value=4096+i*100
        records.append(record)
    def iterate():
        yield from records
        if broken_iteration:raise ValueError('broken tail')
    log.records.side_effect=iterate
    monkeypatch.setattr(module,'Evtx',lambda _:log)
    path=tmp_path/'test.evtx';path.write_bytes(bytes(4096))
    return path


@pytest.mark.asyncio
async def test_evtx_provider_levels_range_and_latest_sample(monkeypatch,tmp_path):
    path=mock_log(monkeypatch,tmp_path,[event_xml(stamp='2025-05-20T07:00:00Z',rid=1),
        event_xml(stamp='2025-05-20T10:00:00Z',rid=2),event_xml(stamp='2025-05-20T17:00:00+08:00',rid=3)])
    result=await EvtxExtractor(sample_size=2).extract_result(str(path))
    assert result.status=='partial'
    assert [r['record_id'] for r in result.records]==[2,3]
    assert result.coverage['earliest_utc']=='2025-05-20T07:00:00+00:00'
    assert result.coverage['latest_utc']=='2025-05-20T10:00:00+00:00'
    assert '远程桌面' not in result.text and 'Shell' not in result.text
    assert '信息' in result.text and '未提供事件说明' in result.text
    assert LEVEL_NAMES=={0:'始终记录',1:'严重',2:'错误',3:'警告',4:'信息',5:'详细'}


@pytest.mark.asyncio
async def test_evtx_missing_time_and_record_errors_have_coverage(monkeypatch,tmp_path):
    path=mock_log(monkeypatch,tmp_path,[event_xml(stamp='not-a-time'),'<bad xml'],broken_iteration=True)
    result=await EvtxExtractor().extract_result(str(path))
    assert result.status=='partial'
    assert result.records[0]['timestamp_utc'] is None
    assert result.coverage['failed_records']==1 and result.coverage['unknown_time_records']==1
    assert 'EVTX_ITERATION_INCOMPLETE' in result.diagnostics


@pytest.mark.asyncio
async def test_empty_optional_integer_fields_do_not_drop_valid_records(monkeypatch,tmp_path):
    xml=event_xml().replace('<EventID>22</EventID>','<EventID/>').replace('<Level>4</Level>','<Level>invalid</Level>')
    path=mock_log(monkeypatch,tmp_path,[xml])
    result=await EvtxExtractor().extract_result(str(path))
    assert result.status=='partial' and result.coverage['record_count']==1
    assert result.coverage['failed_records']==0
    assert result.records[0]['event_id'] is None and result.records[0]['level'] is None


@pytest.mark.asyncio
async def test_latest_sample_respects_100ns_source_precision(monkeypatch,tmp_path):
    path=mock_log(monkeypatch,tmp_path,[event_xml(stamp='2025-05-20T09:00:00.1234569Z',rid=1),
                                      event_xml(stamp='2025-05-20T09:00:00.1234561Z',rid=2)])
    result=await EvtxExtractor(sample_size=1).extract_result(str(path))
    assert result.records[0]['record_id']==1
    assert result.records[0]['raw_timestamp']=='2025-05-20T09:00:00.1234569Z'


@pytest.mark.asyncio
async def test_evtx_bad_checksum_and_empty_log_not_evidence(monkeypatch,tmp_path):
    path=mock_log(monkeypatch,tmp_path,[event_xml()],checksum=False)
    bad=await EvtxExtractor().extract_result(str(path))
    assert bad.status=='error' and not bad.text and not bad.records
    path=mock_log(monkeypatch,tmp_path,[])
    empty=await EvtxExtractor().extract_result(str(path))
    assert empty.status=='metadata_only' and empty.coverage['record_count']==0
    with pytest.raises(DocumentContentUnavailableError):empty.require_content()


def test_native_evtx_rejects_wrong_record_identity():
    import ctypes
    from httpserver.services.extractors.windows_evtx_native import NativeEvtxReader
    reader=NativeEvtxReader('unused')
    reader._open=lambda:True
    def get_record(handle,index,record,error):
        ctypes.cast(record,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.c_void_p(1)
        return 1
    def get_id(record,identifier,error):
        ctypes.cast(identifier,ctypes.POINTER(ctypes.c_uint64))[0]=7
        return 1
    reader._get=get_record;reader._id=get_id;reader._record_free=MagicMock()
    with pytest.raises(ValueError,match='EVTX_NATIVE_RECORD_ID_MISMATCH'):
        reader.read_xml(0,8)
    reader._record_free.assert_called_once()


@pytest.mark.asyncio
async def test_legacy_parser_error_is_not_content():
    class Broken(BaseExtractor):
        async def extract_to_markdown(self,path):return 'Error: missing parser'
    with pytest.raises(DocumentContentUnavailableError):
        await Broken().extract_to_markdown_detailed('broken.lnk')


@pytest.mark.asyncio
async def test_actual_document_error_quote_is_preserved():
    from httpserver.services.extractors.markitdown_extractor import MarkitdownExtractor
    extractor=object.__new__(MarkitdownExtractor)
    extractor._md=MagicMock();extractor._fallback_map={}
    text='Error: connection refused\n这行错误记录来自原始文档。'
    extractor._md.convert.return_value=MagicMock(markdown=text,title=None)
    result=await extractor.extract_result('source.pdf')
    assert result.require_content()==text


@pytest.mark.asyncio
async def test_workbench_does_not_fall_back_to_raw_after_parser_error(tmp_path,monkeypatch):
    from httpserver.services.investigation_service import InvestigationService
    from httpserver.services import document_extractor
    class Broken(BaseExtractor):
        async def extract_to_markdown(self,path):return 'Error: missing parser'
    path=tmp_path/'broken.lnk';path.write_text('RAW_FALLBACK_MUST_NOT_BECOME_EVIDENCE')
    locator=MagicMock();locator.get_extractor.return_value=Broken()
    monkeypatch.setattr(document_extractor,'get_document_extractor_locator',lambda:locator)
    with pytest.raises(DocumentContentUnavailableError):
        await InvestigationService._extract_file_text(None,str(path))


@pytest.mark.asyncio
async def test_upload_returns_unknown_content_error_without_model_call(monkeypatch):
    from io import BytesIO
    from fastapi import UploadFile, HTTPException
    from unittest.mock import AsyncMock
    from httpserver.routes.llm_endpoints import _analysis
    from httpserver import services
    class Broken(BaseExtractor):
        async def extract_to_markdown(self,path):return 'Error: missing parser'
    locator=MagicMock();locator.get_extractor.return_value=Broken()
    manager=MagicMock();manager.llm_service.analyze=AsyncMock()
    monkeypatch.setattr(services,'get_document_extractor_locator',lambda:locator)
    monkeypatch.setattr(services,'get_service_manager',lambda:manager)
    file=UploadFile(filename='broken.lnk',file=BytesIO(b'broken'))
    with pytest.raises(HTTPException) as error:
        await _analysis.analyze_uploaded_file(file=file,model_type='text',prompt=None,settings=MagicMock())
    assert error.value.status_code==422
    assert error.value.detail['code']=='PARSER_DIAGNOSTIC_NOT_EVIDENCE'
    manager.llm_service.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_freeze_keeps_lnk_diagnostic_out_of_material(tmp_path,monkeypatch):
    import sqlite3
    from types import SimpleNamespace as Obj
    from httpserver.services import document_extractor
    from httpserver.services.forensic_report.generation_sources import freeze_materials
    class Broken(BaseExtractor):
        async def extract_to_markdown(self,path):return 'Error: missing parser'
    locator=MagicMock();locator.get_extractor.return_value=Broken()
    monkeypatch.setattr(document_extractor,'get_document_extractor_locator',lambda:locator)
    root=tmp_path/'extracted_files';root.mkdir()
    (root/'a.lnk').write_bytes(b'broken')
    dbpath=tmp_path/'files.db'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE files(path TEXT,md5 TEXT)')
        db.execute('INSERT INTO files VALUES(?,?)',('/a.lnk',''))
    task={'id':'A','output_files_db':str(dbpath),'extraction_directory':str(root)}
    item=Obj(evidence_key='file:/a.lnk',snapshot=Obj(evidence_type='file',
        payload=Obj(normalized_path='/a.lnk',md5=None,size=6)))
    material=(await freeze_materials(task,[item]))[0]
    assert material.status=='unavailable' and material.text==''
    assert 'PARSER_DIAGNOSTIC_NOT_EVIDENCE' in material.limitations
