"""Neutral, source-bound semantic probes for the existing selection stage."""
import asyncio
import hashlib
import json
import time
import subprocess
import sys
import os
import tempfile
from pathlib import Path
from .source_reading import ensure_source,connect,MAX_SOURCE_BYTES,MAX_BUNDLE_BYTES
from .source_identity import file_row,SourceIdentityError
from contextlib import closing


async def probe_sources(task,sources,*,backend,max_bytes,max_files,timeout_seconds):
    result={};reserved=processed=0;start=time.monotonic()
    temporary=tempfile.TemporaryDirectory(prefix='tracelens-selection-probe-')
    env={**os.environ,'TMPDIR':temporary.name,'TEMP':temporary.name,'TMP':temporary.name,'TRACELENS_PROBE_WORKER':'1'}
    worker=await asyncio.create_subprocess_exec(sys.executable,'-B','-m','httpserver.services.candidate_probe','--worker',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
        env=env,limit=128*1024)
    try:
        for entry in sources[:max_files]:
            if time.monotonic()-start>=timeout_seconds:break
            sid=entry['source_id'];path=entry['path']
            try:
                with closing(connect(task['output_files_db'])) as db:
                    row,_=file_row(db,path,sid)
                    sizes=[int(row.get('size') or 0)]
                    # Reserve companions before materialization; ambiguity must be
                    # resolved by the shared reader, never by selecting the first.
                    for suffix in ('-wal','-journal'):
                        sizes.extend(max(0,int(r[0] or 0)) for r in db.execute('SELECT size FROM source_objects WHERE path=?',(path+suffix,)))
                amount=sum(sizes)
                if any(n>MAX_SOURCE_BYTES for n in sizes) or amount>MAX_BUNDLE_BYTES or amount>max_bytes-reserved:
                    result[sid]={'state':'unprobed','reason':'语义探测读取额度不足'};continue
                reserved+=amount;processed+=1
                bundle=await ensure_source(task,path,sid,cpp_backend=backend)
                # Run parser work off the event loop; one probe is at most the
                # source read budget. Format-specific readers enforce their limits.
                remaining=max(0.01,timeout_seconds-(time.monotonic()-start))
                payload={'task':{k:v for k,v in task.items() if k in ('id','output_files_db','extraction_directory','android_source','image_path')},'path':path,'source_id':sid}
                worker.stdin.write((json.dumps(payload)+'\n').encode())
                await worker.stdin.drain()
                line=await asyncio.wait_for(worker.stdout.readline(),timeout=min(remaining,20))
                if not line:
                    result[sid]={'state':'unprobed','reason':'探测进程资源超限或异常退出'};break
                result[sid]=json.loads(line)
            except asyncio.TimeoutError:
                # The finally block kills/reaps the process and removes its private
                # snapshot root. No abandoned native parser thread.
                result[sid]={'state':'unprobed','reason':'语义探测达到时间上限'};break
            except Exception as exc:
                result[sid]={'state':'error','reason':getattr(exc,'code','SOURCE_PROBE_FAILED')}
    finally:
        if worker.returncode is None:
            worker.kill()
        await worker.wait()
        temporary.cleanup()
    return {'results':result,'reserved_bytes':reserved,'processed':processed,
            'budget_exhausted':processed<len(sources),'accounting':'source_component_bytes'}


def _worker(payload):
    from .source_reading import resolve_source
    bundle=resolve_source(payload['task'],payload['path'],payload['source_id'])
    with bundle.snapshot() as (copy,hashes,provenance):
        with copy.open('rb') as stream:head=stream.read(64)
        suffix=copy.suffix.lower()
        if copy.name in ('wtmp','utmp','btmp'):
            from .extractors.linux_utmp import LinuxUtmpExtractor
            extractor=LinuxUtmpExtractor(max_records=128)
        elif head.startswith(b'SQLite format 3\0'):
            from .extractors.sqlite_records import SQLiteExtractor
            extractor=SQLiteExtractor(sample_size=5)
        elif head.startswith(b'regf') or suffix=='.hve':
            from .extractors.windows_registry import RegistryExtractor
            extractor=RegistryExtractor()
        elif head.startswith(b'ElfFile\0') or suffix=='.evtx':
            from .extractors.windows_evtx_records import EvtxExtractor
            extractor=EvtxExtractor(sample_size=5,max_scan_records=128)
        elif head.startswith(b'MAM') or head[4:8]==b'SCCA' or suffix=='.pf':
            from .extractors.windows_prefetch import PrefetchExtractor
            extractor=PrefetchExtractor()
        elif suffix=='.lnk':
            from .extractors.windows_lnk import LnkExtractor
            extractor=LnkExtractor()
        elif head.startswith(b'\x7fELF') and len(head)>=16 and head[4] in (1,2) and head[5] in (1,2) and head[6]==1:
            return {'state':'signature_confirmed','format':'executable'}
        elif suffix in {'.txt','.json','.xml','.ini','.conf','.cfg','.log','.csv','.md','.sh','.ps1','.yaml','.yml','.php','.phtml','.jsp','.asp','.aspx','.py','.js','.ts'} or head.startswith((b'\xff\xfe',b'\xfe\xff')):
            from .extractors.text_dump import TextDumpExtractor
            extractor=TextDumpExtractor(max_bytes=65536)
        else:extractor=None
        if head.startswith(b'MZ') and len(head)>=64:
            offset=int.from_bytes(head[60:64],'little')
            if offset<=copy.stat().st_size-4:
                with copy.open('rb') as stream:
                    stream.seek(offset)
                    if stream.read(4)==b'PE\0\0':return {'state':'signature_confirmed','format':'executable'}
        # Probe only local bounded parsers; Office/media remote conversions stay
        # in the formal analysis stage and are never called from a probe.
        if extractor is None or type(extractor).__name__ not in {
            'SQLiteExtractor','RegistryExtractor','PrefetchExtractor','WindowsPrefetchExtractor',
            'EvtxExtractor','WindowsEvtxExtractor','LnkExtractor','TextDumpExtractor','LinuxUtmpExtractor'}:
            return {'state':'unprobed','reason':'此格式没有已配置的有界语义探测器'}
        parsed=asyncio.run(extractor.extract_result(str(copy)))
        if 'EVTX_PROBE_SCAN_LIMIT' in parsed.diagnostics and not parsed.coverage.get('parsed_record_count'):
            return {'state':'unprobed','reason':'抽样窗口内尚无可读记录，未推断全文件无内容','coverage':parsed.coverage}
        kind={'SQLiteExtractor':'sqlite','RegistryExtractor':'registry','PrefetchExtractor':'prefetch','EvtxExtractor':'evtx','LnkExtractor':'lnk','TextDumpExtractor':'text','LinuxUtmpExtractor':'linux_utmp'}.get(type(extractor).__name__,'unknown')
        value={'state':parsed.status,'format':kind,'parser':parsed.parser,'parser_version':parsed.parser_version,
               'coverage':parsed.coverage,'diagnostics':list(parsed.diagnostics),
               'preview':parsed.text[:512] if parsed.status in ('ok','partial') else ''}
        components=[{k:c.get(k) for k in ('role','sha256','size')} for c in provenance['components']]
        value['bundle_sha256']=hashlib.sha256(json.dumps(components,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return value


if __name__=='__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU,(300,301))
    except (ImportError,ValueError,OSError):pass
    for line in sys.stdin:
        try:
            if len(line)>65536:raise ValueError('PROBE_REQUEST_TOO_LARGE')
            value=_worker(json.loads(line))
        except MemoryError:value={'state':'unprobed','reason':'语义探测内存预算不足'}
        except Exception as exc:value={'state':'error','reason':getattr(exc,'code','SOURCE_PROBE_FAILED')}
        print(json.dumps(value,ensure_ascii=False),flush=True)
