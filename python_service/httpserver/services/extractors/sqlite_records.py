"""Bounded SQLite projections with explicit row locators and WAL provenance."""
import hashlib
import sqlite3
import time
from .base import BaseExtractor, ExtractionResult, DocumentContentUnavailableError, register_extractor
from .sqlite_snapshot import sqlite_snapshot


def identifier(value):
    return '"'+value.replace('"','""')+'"'


def cell(value):
    if isinstance(value,bytes):return {'blob_size':len(value),'blob_sha256':hashlib.sha256(value).hexdigest()}
    if isinstance(value,str) and len(value)>300:
        return {'text':value[:300],'truncated':True,'characters':len(value),'sha256':hashlib.sha256(value.encode()).hexdigest()}
    return value


@register_extractor
class SQLiteExtractor(BaseExtractor):
    def __init__(self,sample_size=50):
        self.sample_size=max(1,min(int(sample_size),500))

    async def extract_to_markdown(self,file_path):
        return (await self.extract_result(file_path)).require_content()

    async def extract_result(self,file_path):
        with open(file_path,'rb') as stream:
            if stream.read(16)!=b'SQLite format 3\0':
                raise DocumentContentUnavailableError('文件不是可读的 SQLite 数据库',code='SQLITE_SIGNATURE_INVALID')
        try:
            return self._read(file_path)
        except DocumentContentUnavailableError:raise
        except sqlite3.Error as exc:
            raise DocumentContentUnavailableError('数据库快照无法只读解析',code='SQLITE_READ_FAILED') from exc

    def _read(self,file_path):
        records=[];warnings=[];tables_coverage=[]
        with sqlite_snapshot(file_path) as (db,source):
            deadline=time.monotonic()+15
            db.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
            total=db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
            tables=db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 64").fetchall()
            lines=['# SQLite 数据库记录',f'表总数：{total}；已读表：{len(tables)}；每表最多抽样 {self.sample_size} 行。']
            if source['wal']:
                lines.append(f"WAL 已校验：{source['wal']['frames']} 帧；截至第 {source['wal']['committed_frames']} 帧的已提交视图。")
            if total>len(tables):warnings.append('SQLITE_TABLE_LIMIT')
            used=0
            for name,schema in tables:
                if used>50000:
                    warnings.append('SQLITE_TEXT_LIMIT');break
                info=db.execute(f'PRAGMA table_info({identifier(name)})').fetchall()
                names=[r[1] for r in info]
                keys=[r[1] for r in sorted(info,key=lambda r:r[5]) if r[5]]
                hidden=next((v for v in ('_rowid_','rowid','oid') if v not in {n.lower() for n in names}),None)
                without_rowid='WITHOUT ROWID' in (schema or '').upper()
                try:
                    count=db.execute(f'SELECT COUNT(*) FROM {identifier(name)}').fetchone()[0]
                    order=','.join(identifier(k) for k in keys) if keys else (hidden or '')
                    prefix=f'{hidden},' if hidden and not without_rowid else ''
                    query=f'SELECT {prefix}* FROM {identifier(name)}'+(f' ORDER BY {order}' if order else '')+' LIMIT ?'
                    rows=db.execute(query,(self.sample_size,)).fetchall()
                    tables_coverage.append({'table':name,'total_rows':count,'sampled_rows':len(rows)})
                    if count>len(rows):warnings.append('SQLITE_ROWS_SAMPLED')
                    lines.extend(['',f'## 表 `{name}`',f'记录数：{count}；本次展示：{len(rows)}。','```sql',schema or '', '```'])
                    for index,row in enumerate(rows):
                        values=row[1:] if prefix else row
                        fields={n:cell(v) for n,v in zip(names,values)}
                        locator={'table':name}
                        if keys:locator['primary_key']={k:fields[k] for k in keys}
                        elif prefix:locator['rowid']=row[0]
                        else:locator.update(sample_ordinal=index,locator_basis='frozen_projection_order');warnings.append('SQLITE_ROW_LOCATOR_LIMITED')
                        text='；'.join(f'{k}={v}' for k,v in fields.items()).replace('\n',' ')
                        if used+len(text)>50000:
                            warnings.append('SQLITE_TEXT_LIMIT')
                            tables_coverage[-1]['sampled_rows']=index
                            break
                        records.append({'locator':locator,'fields':fields})
                        lines.append('- '+text);used+=len(text)
                except sqlite3.Error:
                    warnings.append('SQLITE_TABLE_UNREADABLE')
                    tables_coverage.append({'table':name,'status':'unavailable'})
            text='\n'.join(lines)
            coverage={'table_count':total,'tables':tables_coverage,'source_snapshot':source,'record_count':len(records)}
            return ExtractionResult('partial' if warnings else 'ok','sqlite3',sqlite3.sqlite_version,text=text,
                                    records=tuple(records),diagnostics=tuple(sorted(set(warnings))),coverage=coverage,diagnostics_separated=True)
