import struct
import pytest
from httpserver.services.extractors.linux_utmp import LinuxUtmpExtractor
from httpserver.services.document_extractor import get_document_extractor_locator


def record(index=0,kind=7,seconds=1653379200):
    row=bytearray(384);struct.pack_into('<h',row,0,kind);struct.pack_into('<i',row,4,123)
    row[8:13]=b'pts/0';row[44:48]=b'root';row[76:85]=b'192.0.2.1'
    struct.pack_into('<ii',row,340,seconds,123000)
    return bytes(row)


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['wtmp', 'utmp', 'btmp', 'login.wtmp', 'login.utmp', 'login.btmp'])
async def test_glibc_layout_and_utc_are_taken_from_correct_fields(tmp_path, name):
    path=tmp_path/name;path.write_bytes(record())
    parser=get_document_extractor_locator().get_extractor(str(path))
    assert isinstance(parser,LinuxUtmpExtractor)
    result=await parser.extract_result(str(path));row=result.records[0]
    assert row['user']=='root' and row['terminal']=='pts/0' and row['hostname']=='192.0.2.1'
    assert row['timestamp_utc']=='2022-05-24T08:00:00.123000Z'
    assert row['byte_offset']==0 and result.status=='ok'
    assert len(result.text)<4000


@pytest.mark.asyncio
async def test_unknown_time_and_truncated_tail_do_not_invent_a_login(tmp_path):
    path=tmp_path/'wtmp';path.write_bytes(record(seconds=0)+b'partial')
    result=await LinuxUtmpExtractor().extract_result(str(path))
    assert result.status=='partial' and result.records[0]['timestamp_utc'] is None
    assert 'UTMP_TRAILING_BYTES' in result.diagnostics
    assert '1970-' not in result.text


@pytest.mark.asyncio
async def test_budget_samples_both_ends_with_actual_offsets(tmp_path):
    path=tmp_path/'wtmp';path.write_bytes(b''.join(record(i,seconds=1653379200+i) for i in range(12)))
    result=await LinuxUtmpExtractor(max_records=4).extract_result(str(path))
    assert result.status=='partial'
    assert [r['byte_offset'] for r in result.records]==[0,384,3840,4224]
    assert result.coverage['scanned_records']==4 and result.coverage['total_record_slots']==12


@pytest.mark.asyncio
async def test_corrupt_type_is_not_a_successful_record(tmp_path):
    path=tmp_path/'wtmp';path.write_bytes(record(kind=500))
    result=await LinuxUtmpExtractor().extract_result(str(path))
    assert result.status=='error' and not result.text and not result.records
