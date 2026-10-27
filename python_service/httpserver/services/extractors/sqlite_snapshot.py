"""Capture SQLite components before opening a parser connection."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import struct
import tempfile
from .base import DocumentContentUnavailableError


def wal_coverage(database, wal):
    header=Path(database).open('rb')
    try:main=header.read(100)
    finally:header.close()
    size=Path(wal).stat().st_size
    if size==0:return {'frames':0,'committed_frames':0,'uncommitted_tail_frames':0}
    with Path(wal).open('rb') as stream:
        head=stream.read(32)
        if len(head)!=32:raise DocumentContentUnavailableError('WAL 头部不完整',code='SQLITE_WAL_TRUNCATED')
        magic,version,page_size=struct.unpack('>III',head[:12])
        main_size=int.from_bytes(main[16:18],'big');main_size=65536 if main_size==1 else main_size
        if magic not in (0x377f0682,0x377f0683) or version!=3007000 or page_size!=main_size or page_size<512 or page_size>65536 or page_size&(page_size-1):
            raise DocumentContentUnavailableError('WAL 与数据库不兼容',code='SQLITE_WAL_INCOMPATIBLE')
        endian='<' if magic==0x377f0682 else '>'
        def checksum(data,a,b):
            for x,y in struct.iter_unpack(endian+'II',data):
                a=(a+x+b)&0xffffffff;b=(b+y+a)&0xffffffff
            return a,b
        a,b=checksum(head[:24],0,0)
        if (a,b)!=struct.unpack('>II',head[24:]):raise DocumentContentUnavailableError('WAL 校验和不符',code='SQLITE_WAL_CHECKSUM_MISMATCH')
        frames=committed=0
        while frame:=stream.read(24):
            page=stream.read(page_size)
            if len(frame)!=24 or len(page)!=page_size:raise DocumentContentUnavailableError('WAL 帧不完整',code='SQLITE_WAL_TRUNCATED')
            if frame[8:16]!=head[16:24] or int.from_bytes(frame[:4],'big')==0:
                raise DocumentContentUnavailableError('WAL 帧来源不一致',code='SQLITE_WAL_FRAME_MISMATCH')
            a,b=checksum(frame[:8]+page,a,b)
            if (a,b)!=struct.unpack('>II',frame[16:24]):raise DocumentContentUnavailableError('WAL 帧校验和不符',code='SQLITE_WAL_CHECKSUM_MISMATCH')
            frames+=1
            if int.from_bytes(frame[4:8],'big'):committed=frames
        return {'frames':frames,'committed_frames':committed,'uncommitted_tail_frames':frames-committed}


@contextmanager
def sqlite_snapshot(file_path):
    from ..source_reading import digest_copy, MAX_SOURCE_BYTES, MAX_BUNDLE_BYTES
    source=Path(file_path)
    with tempfile.TemporaryDirectory(prefix='tracelens-sqlite-') as folder:
        target=Path(folder)/source.name
        components=[dict(digest_copy(source,target,MAX_SOURCE_BYTES),role='primary')]
        used=components[0]['size'];coverage={}
        for suffix,role in (('-wal','wal'),('-journal','journal')):
            companion=Path(str(source)+suffix)
            if companion.is_file():
                captured=Path(str(target)+suffix)
                component=dict(digest_copy(companion,captured,min(MAX_SOURCE_BYTES,MAX_BUNDLE_BYTES-used)),role=role)
                used+=component['size'];components.append(component)
                if role=='wal':coverage=wal_coverage(target,captured)
        uri=target.as_uri()+'?mode=ro'
        conn=sqlite3.connect(uri,uri=True,timeout=5)
        try:
            conn.execute('PRAGMA query_only=ON')
            yield conn,{'components':components,'wal':coverage,'view':'read_only_committed_sqlite','sqlite_version':sqlite3.sqlite_version}
        finally:conn.close()
