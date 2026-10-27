"""Offline cold-run/resume acceptance using synthetic Windows artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import zlib


def main(binary):
    if not shutil.which('mkfs.ext4'):
        print('SKIP: mkfs.ext4 is unavailable')
        return 77
    fixtures=Path(__file__).resolve().parents[1]/'fixtures/windows_parser_truth'
    with tempfile.TemporaryDirectory(prefix='tracelens-parser-truth-') as folder:
        base=Path(folder);root=base/'tree'
        pf=root/'Windows/Prefetch';logs=root/'Windows/System32/winevt/Logs'
        pf.mkdir(parents=True);logs.mkdir(parents=True)
        for name in ('synthetic_v17.pf','synthetic_v17_mam.pf'):
            shutil.copyfile(fixtures/name,pf/name)
        (pf/'broken.pf').write_bytes(b'MAM\x04'+struct.pack('<I',4096)+bytes(32))
        header=bytearray(4096);header[:8]=b'ElfFile\0'
        struct.pack_into('<I',header,32,128);struct.pack_into('<HHHH',header,36,2,3,4096,0)
        struct.pack_into('<I',header,124,zlib.crc32(header[:120]))
        (logs/'Empty.evtx').write_bytes(header);(logs/'Broken.evtx').write_bytes(b'broken')
        image=base/'fixture.img'
        with image.open('wb') as stream:stream.truncate(64*1024*1024)
        subprocess.run(['mkfs.ext4','-q','-F','-d',str(root),str(image)],check=True)
        before=hashlib.sha256(image.read_bytes()).hexdigest()
        env=os.environ.copy()
        env.update(PROJECT_ROOT=str(Path(__file__).resolve().parents[2]),DATA_DIR=str(base/'data'),
                   DB_OUTPUT_DIR=str(base/'out'),WIN_LINUX_ARTIFACT_LLM_ENABLED='false')
        command=[str(binary),str(image),'--windows-analyze','--no-ai','--db-dir',str(base/'out')]
        for iteration in range(2):
            run=subprocess.run(command,env=env,cwd=base,capture_output=True,text=True,timeout=120)
            assert run.returncode==0,run.stdout+run.stderr
            assert ('[Windows] Analyzing' if iteration==0 else 'Platform analysis... skipped') in run.stdout,run.stdout
            with sqlite3.connect(f'file:{base}/out/fixture_files.db?mode=ro',uri=True) as db:
                rows=db.execute('SELECT run_count,last_run_time,parse_status FROM prefetch_files ORDER BY id').fetchall()
                assert len(rows)==3,rows
                assert sum(r==(2,1747731064,'ok') for r in rows)==2,rows
                assert (None,None,'error') in rows,rows
                outcomes=db.execute('SELECT source_path,status,record_count FROM parser_outcomes').fetchall()
                assert any(p.endswith('Empty.evtx') and s=='metadata_only' and n==0 for p,s,n in outcomes),outcomes
                assert any(p.endswith('Broken.evtx') and s=='error' and n is None for p,s,n in outcomes),outcomes
                if iteration==0:initial=(rows,outcomes)
                else:assert (rows,outcomes)==initial,'resume duplicated or reinterpreted artifacts'
            with sqlite3.connect(f'file:{base}/out/fixture_events.db?mode=ro',uri=True) as timeline:
                execution=timeline.execute("SELECT timestamp,source_id FROM events WHERE event_type='PREFETCH_EXECUTION' ORDER BY id").fetchall()
                assert execution and all(t==1747731064 and key.startswith('winactivity:') for t,key in execution),execution
                assert timeline.execute('SELECT COUNT(*) FROM windows_activity_records').fetchone()[0]>=3
                if iteration==0:initial_execution=execution
                else:assert execution==initial_execution,'续跑重复导入Windows活动'
        assert before==hashlib.sha256(image.read_bytes()).hexdigest()
        print('PASS: 首次解析、未知值、空日志、错误隔离、续跑幂等、检材保持不变')
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analyzer',type=Path,required=True)
    raise SystemExit(main(parser.parse_args().analyzer.resolve()))
