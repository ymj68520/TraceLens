"""Bounded, read-only source resolution and isolated parser snapshots.

Every parser receives the original logical basename. SQLite companions are
copied only from the same validated source group, never from a guessed folder.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from .source_identity import SourceIdentityError, file_row, lookup_locator, locator_hash, decode_reference, analysis_reference
from .extraction_layout import candidate_roots

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_BUNDLE_BYTES = 320 * 1024 * 1024
_active_sources = ContextVar('active_source_reads', default={})


def source_reference_for_read(path):
    """Keep media caches and downstream saves keyed by the source, not a temp path."""
    return _active_sources.get().get(str(path), str(path))


def source_display_path(path):
    return decode_reference(source_reference_for_read(path))[0]


def connect(path):
    try:
        return sqlite3.connect(f"file:{quote(str(Path(path).resolve()),safe='/')}?mode=ro",uri=True)
    except sqlite3.DatabaseError as exc:
        raise SourceIdentityError('SOURCE_INDEX_UNAVAILABLE','任务的来源索引无法只读打开') from exc


def safe_file(root, relative):
    root=Path(root)
    relative=Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise SourceIdentityError('SOURCE_PATH_OUTSIDE_EXTRACTION_ROOT')
    candidate=root/relative
    # Inspect each component, not only resolve()'s final target.
    for part in (root,*candidate.parents,candidate):
        if part.is_symlink(): raise SourceIdentityError('SOURCE_SYMLINK_REJECTED')
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise SourceIdentityError('SOURCE_PATH_OUTSIDE_EXTRACTION_ROOT')
    return candidate


def logical_name(row):
    name=row.get('name') or str(row['path']).replace('\\','/').rsplit('/',1)[-1]
    if not name or name in ('.','..') or '/' in name or '\\' in name:
        raise SourceIdentityError('SOURCE_NAME_INVALID')
    return name


def digest_copy(source, target, limit, expected=None):
    if source.is_symlink(): raise SourceIdentityError('SOURCE_SYMLINK_REJECTED')
    before=source.stat()
    if before.st_size>limit: raise SourceIdentityError('SOURCE_EXCEEDS_READ_BUDGET')
    sha,md5=hashlib.sha256(),hashlib.md5()
    count=0
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
    with os.fdopen(os.open(source,flags),'rb') as stream, target.open('wb') as output:
        actual=os.fstat(stream.fileno())
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(actual.st_ino,actual.st_size,actual.st_mtime_ns):
            raise SourceIdentityError('SOURCE_CHANGED_DURING_READ')
        while chunk:=stream.read(min(1024*1024,limit-count+1)):
            count+=len(chunk)
            if count>limit:raise SourceIdentityError('SOURCE_EXCEEDS_READ_BUDGET')
            sha.update(chunk);md5.update(chunk);output.write(chunk)
    after=source.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns) or count!=before.st_size:
        raise SourceIdentityError('SOURCE_CHANGED_DURING_READ')
    result={'sha256':sha.hexdigest(),'md5':md5.hexdigest(),'size':count}
    if expected and ((expected.get('sha256') and expected['sha256']!=result['sha256']) or
                     (expected.get('size') is not None and expected['size']!=count)):
        raise SourceIdentityError('SOURCE_HASH_CHANGED')
    return result


def content_fingerprint(path):
    before=path.stat()
    if before.st_size>MAX_SOURCE_BYTES:raise SourceIdentityError('SOURCE_EXCEEDS_READ_BUDGET')
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):sha.update(chunk)
    after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
        raise SourceIdentityError('SOURCE_CHANGED_DURING_READ')
    return sha.hexdigest(),after.st_size


@dataclass
class SourceBundle:
    row: dict
    path: Path
    locator: dict | None = None
    source_id: str | None = None
    components: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @contextmanager
    def snapshot(self, max_bytes=MAX_SOURCE_BYTES):
        """The caller owns a disposable copy; parser side effects cannot touch evidence."""
        name=logical_name(self.row)
        with tempfile.TemporaryDirectory(prefix='tracelens-source-') as directory:
            root=Path(directory);copy=root/name
            primary=next((v for v in self.components if v['role']=='primary'),None)
            hashes=digest_copy(self.path,copy,max_bytes,primary)
            if self.row.get('size') is not None and hashes['size']!=self.row['size']:
                raise SourceIdentityError('SOURCE_SIZE_CHANGED')
            md5=self.row.get('md5') or ''
            if len(md5)==32 and md5.lower()!=hashes['md5']:
                raise SourceIdentityError('SOURCE_HASH_CHANGED')
            captured=[dict(hashes,role='primary',logical_name=name,source_id=self.source_id)]
            used=hashes['size']
            for component in self.components:
                if component['role']=='primary':continue
                filename=component['file_name']
                if filename not in (name+'-wal',name+'-journal'):
                    raise SourceIdentityError('COMPANION_NAME_MISMATCH')
                source=safe_file(self.path.parent,filename)
                hashes_comp=digest_copy(source,root/filename,min(MAX_SOURCE_BYTES,MAX_BUNDLE_BYTES-used),component)
                used+=hashes_comp['size']
                captured.append(dict(hashes_comp,role=component['role'],logical_name=filename,source_id=component.get('source_id')))
            provenance={'version':1,'source_id':self.source_id,'locator':self.locator,
                        'logical_name':name,'hash_scope':'extracted_components','components':captured}
            token=_active_sources.set({**_active_sources.get(),str(copy):analysis_reference(self.row['path'],self.source_id)})
            try:
                yield copy,hashes,provenance
            finally:
                _active_sources.reset(token)


def resolve_source(task, path, source_id=None, expected=None):
    path, embedded=decode_reference(path)
    if source_id and embedded and source_id!=embedded:
        raise SourceIdentityError('SOURCE_PATH_ID_MISMATCH')
    source_id=source_id or embedded
    db_path=Path(task['output_files_db'])
    with closing(connect(db_path)) as db:
        row,locator=file_row(db,path,source_id)
        if (row.get('size') or 0)>MAX_SOURCE_BYTES:
            raise SourceIdentityError('SOURCE_EXCEEDS_READ_BUDGET')
        if expected:
            for field in ('size','mtime','ctime','is_deleted'):
                value=getattr(expected,field,None)
                if value is not None and field in row and row[field] is not None and row[field]!=value:
                    raise SourceIdentityError('SOURCE_RECORD_CHANGED')
                if value is not None and row.get(field) is None:
                    row[field]=value
            expected_md5=getattr(expected,'md5',None)
            if expected_md5 and row.get('md5') and expected_md5.lower()!=row['md5'].lower():
                raise SourceIdentityError('SOURCE_HASH_CHANGED')
            if expected_md5 and not row.get('md5'):
                row['md5']=expected_md5
        effective_id=source_id or row.get('source_id')
        if effective_id:
            locator=lookup_locator(db,effective_id)
        recorded=Path(task.get('extraction_directory') or db_path.parent/'extracted_files')
        roots=[p for p in candidate_roots(recorded) if not p.is_symlink()]
        if task.get('android_source')=='dir' and task.get('image_path'):
            roots.append(Path(task['image_path']))
        manifests=[]
        if effective_id:
            for root in roots:
                manifest_path=safe_file(root,Path('by-source')/effective_id/'source.json')
                if manifest_path.is_file():manifests.append(manifest_path)
        if len(manifests)>1:raise SourceIdentityError('EXTRACTED_SOURCE_AMBIGUOUS')
        if manifests:
            manifest=json.loads(manifests[0].read_text(encoding='utf-8'))
            if manifest.get('source_id')!=effective_id or manifest.get('locator')!=locator:
                raise SourceIdentityError('SOURCE_MANIFEST_MISMATCH')
            components=manifest.get('components',[])
            primaries=[c for c in components if c.get('role')=='primary']
            if len(primaries)!=1 or primaries[0].get('file_name')!=logical_name(row):
                raise SourceIdentityError('SOURCE_MANIFEST_INVALID')
            from .source_identity import ID
            if any(not ID.fullmatch(c.get('sha256','')) or not isinstance(c.get('size'),int) or c['size']<0 for c in components):
                raise SourceIdentityError('SOURCE_MANIFEST_INVALID')
            if primaries[0].get('source_id')!=effective_id or len({c.get('role') for c in components})!=len(components):
                raise SourceIdentityError('SOURCE_MANIFEST_INVALID')
            if any(note not in ('COMPANION_WAL_NOT_FOUND','COMPANION_JOURNAL_NOT_FOUND') for note in manifest.get('limitations',[])):
                raise SourceIdentityError('COMPANION_NOT_RELIABLY_READ')
            for component in components:
                if component['role']=='primary':continue
                if component['role'] not in ('wal','journal'):raise SourceIdentityError('SOURCE_MANIFEST_INVALID')
                sibling=lookup_locator(db,component.get('source_id'))
                suffix='-wal' if component['role']=='wal' else '-journal'
                if sibling['source_revision']!=locator['source_revision'] or sibling['logical_path']!=row['path']+suffix or sibling['is_deleted']!=row['is_deleted'] or sibling.get('partition_num')!=locator.get('partition_num'):
                    raise SourceIdentityError('COMPANION_SOURCE_MISMATCH')
                if sibling.get('source_kind')!=locator.get('source_kind') or (component.get('locator') is not None and component['locator']!=sibling):
                    raise SourceIdentityError('COMPANION_SOURCE_MISMATCH')
                if locator.get('source_kind')=='harmony' and any(sibling.get('logical_location',{}).get(k)!=locator.get('logical_location',{}).get(k) for k in ('bundle','app_index')):
                    raise SourceIdentityError('COMPANION_SOURCE_MISMATCH')
            payload_directory=manifest.get('payload_directory','')
            if payload_directory not in ('','payload'):
                raise SourceIdentityError('SOURCE_MANIFEST_INVALID')
            primary_path=safe_file(manifests[0].parent,Path(payload_directory)/logical_name(row))
            if not primary_path.is_file():raise SourceIdentityError('EXTRACTED_SOURCE_MISSING')
            notes=list(manifest.get('limitations',[]))
            if locator.get('name_encoding')=='lossless-component-bytes:v1':
                notes.append('文件名含不可解码或特殊字节；显示名为转义投影，原始路径与名称字节保留在来源定位中')
            return SourceBundle(row,primary_path,locator,effective_id,components,notes)
        if source_id:
            raise SourceIdentityError('EXTRACTED_SOURCE_MISSING')
        # A legacy path is usable only when exact membership and the copy are unique.
        relative=row['path'].replace('\\','/').lstrip('/')
        candidates=set()
        for root in roots:
            candidate=safe_file(root,relative)
            if candidate.is_file():candidates.add(candidate)
        # Some old task indexes explicitly stored workspace absolute paths.
        # Accept those only under a registered root and with exact DB membership.
        indexed_path=Path(row['path'])
        if indexed_path.is_absolute():
            for root in [db_path.parent,*roots]:
                try:
                    inside=indexed_path.relative_to(root)
                except ValueError:
                    continue
                candidate=safe_file(root,inside)
                if candidate.is_file():candidates.add(candidate)
        if not candidates:raise SourceIdentityError('EXTRACTED_SOURCE_MISSING')
        notes=['LEGACY_PATH_ONLY_SOURCE'];components=[]
        if len(candidates)>1:
            fingerprints={content_fingerprint(candidate) for candidate in candidates}
            if len(fingerprints)!=1:raise SourceIdentityError('EXTRACTED_SOURCE_AMBIGUOUS')
            sha,size=fingerprints.pop()
            components.append({'role':'primary','sha256':sha,'size':size})
            notes.append('IDENTICAL_EXTRACTION_COPIES')
        primary=sorted(candidates)[0]
        # Require indexed membership for companions; adjacent host files alone are not proof.
        for suffix,role in (('-wal','wal'),('-journal','journal')):
            try:
                sibling,sibling_locator=file_row(db,row['path']+suffix)
            except SourceIdentityError as exc:
                if exc.code=='SOURCE_NOT_FOUND':continue
                raise SourceIdentityError('COMPANION_SOURCE_AMBIGUOUS') from exc
            if sibling.get('partition_num')!=row.get('partition_num') or sibling.get('is_deleted')!=row.get('is_deleted'):
                raise SourceIdentityError('COMPANION_SOURCE_MISMATCH')
            candidate=safe_file(primary.parent,primary.name+suffix)
            if candidate.is_file():
                # Hashing is performed during capture; legacy companion identity is disclosed.
                components.append({'role':role,'file_name':primary.name+suffix,'source_id':sibling.get('source_id'),
                                   'size':sibling.get('size'),'sha256':None})
        return SourceBundle(row,primary,locator,effective_id,components,notes)


async def ensure_source(task,path,source_id=None,expected=None,cpp_backend=None):
    try:
        return await asyncio.to_thread(resolve_source,task,path,source_id,expected)
    except SourceIdentityError as exc:
        if exc.code!='EXTRACTED_SOURCE_MISSING' or cpp_backend is None:raise
    result=await cpp_backend.materialize_source(task['id'],path,source_id)
    if not isinstance(result,dict):raise SourceIdentityError('SOURCE_BACKEND_INVALID_RESPONSE')
    if not result.get('success'):
        raise SourceIdentityError(result.get('error','SOURCE_MATERIALIZATION_FAILED'),result.get('message','来源提取失败'),candidates=result.get('candidates',()))
    return await asyncio.to_thread(resolve_source,task,path,source_id,expected)


@asynccontextmanager
async def task_source_file(task_id,path,*,source_id=None,files_db_path='',extraction_dir='',task=None,cpp_backend=None,selection_plan_id=None):
    """Shared entry for interactive, batch and case analysis; never resolve host paths first."""
    if task is None:
        if files_db_path:
            task={'id':task_id,'output_files_db':str(files_db_path),'extraction_directory':extraction_dir}
        else:
            if cpp_backend is None:
                from . import get_service_manager
                cpp_backend=get_service_manager().cpp_backend
            task=await cpp_backend.get_task(task_id)
    if not task or not task.get('output_files_db'):
        raise SourceIdentityError('SOURCE_INDEX_UNAVAILABLE')
    task=dict(task,id=task.get('id') or task_id)
    # Legacy callers may send an extracted absolute path. Only registered task
    # roots may be translated; an existing arbitrary host file is never trusted.
    logical,embedded=decode_reference(path)
    if source_id and embedded and source_id!=embedded:
        raise SourceIdentityError('SOURCE_PATH_ID_MISMATCH')
    exact_member=False
    if not (source_id or embedded):
        with closing(connect(task['output_files_db'])) as db:
            try:
                file_row(db,logical)
                exact_member=True
            except SourceIdentityError as exc:
                if exc.code!='SOURCE_NOT_FOUND':raise
    if not (source_id or embedded or exact_member):
        for root in candidate_roots(Path(task.get('extraction_directory') or Path(task['output_files_db']).parent/'extracted_files')):
            try:
                relative=Path(path).relative_to(root)
                if len(relative.parts)==4 and relative.parts[0]=='by-source' and relative.parts[2]=='payload':
                    with closing(connect(task['output_files_db'])) as db:
                        locator=lookup_locator(db,relative.parts[1])
                    if relative.parts[3]!=locator['logical_name']:
                        raise SourceIdentityError('SOURCE_PATH_ID_MISMATCH')
                    source_id=relative.parts[1]
                    logical=locator['logical_path']
                else:
                    logical='/'+relative.as_posix()
                break
            except ValueError:
                continue
    try:
        bundle=await ensure_source(task,logical,source_id or embedded,cpp_backend=cpp_backend)
    except SourceIdentityError as exc:
        if exc.code!='EXTRACTED_SOURCE_MISSING' or cpp_backend is not None or not task_id:
            raise
        from . import get_service_manager
        bundle=await ensure_source(task,logical,source_id or embedded,cpp_backend=get_service_manager().cpp_backend)
    reference=analysis_reference(bundle.row['path'],bundle.source_id)
    from .model_budget import analysis_budget
    with analysis_budget(task['output_files_db'],reference,plan_id=selection_plan_id,task_id=task.get('id')):
        with bundle.snapshot() as (copy,hashes,provenance):
            yield str(copy),reference,provenance
