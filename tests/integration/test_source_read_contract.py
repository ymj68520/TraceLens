"""Offline source-index → materialize → SQLite WAL acceptance, without model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


def main(analyzer,probe):
    with tempfile.TemporaryDirectory(prefix='tracelens-source-contract-') as folder:
        root=Path(folder);tree=root/'tree';tree.mkdir()
        for name in ('source.json','source-1.tmp'):(tree/name).write_text('证据原文 '+name,encoding='utf-8')
        writer=sqlite3.connect(root/'live.db')
        try:
            writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY,note TEXT)');writer.commit()
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            writer.execute("INSERT INTO entries VALUES(1,'仅在 WAL 中的中文记录')");writer.commit()
            shutil.copyfile(root/'live.db',tree/'History');shutil.copyfile(root/'live.db-wal',tree/'History-wal')
        finally:writer.close()
        image=root/'fixture.img'
        with image.open('wb') as output:output.truncate(64*1024*1024)
        subprocess.run(['mkfs.ext4','-q','-F','-d',str(tree),str(image)],check=True)
        before=hashlib.sha256(image.read_bytes()).hexdigest()
        env=os.environ.copy();env.update(PROJECT_ROOT=str(Path(__file__).resolve().parents[2]),DATA_DIR=str(root/'data'),DB_OUTPUT_DIR=str(root/'db'),WIN_LINUX_ARTIFACT_LLM_ENABLED='false')
        run=subprocess.run([str(analyzer),str(image),'--no-ai','--db-dir',str(root/'db')],cwd=root,env=env,capture_output=True,text=True,timeout=120)
        assert run.returncode==0,run.stdout+run.stderr
        raw=root/'db/fixture_raw.db'
        with sqlite3.connect(raw) as db:
            entries=db.execute("SELECT path,name,source_id FROM files WHERE name IN ('source.json','source-1.tmp','History')").fetchall()
            assert len(entries)==3,entries
        for path,name,sid in entries:
            ranged=subprocess.run([str(probe),str(image),str(raw),str(root/'extracted'),'--range',sid],cwd=root,env=env,capture_output=True,text=True,timeout=30)
            assert ranged.returncode==0,ranged.stdout+ranged.stderr
            range_value=json.loads([line for line in ranged.stdout.splitlines() if line.startswith('{')][-1])
            expected=(tree/name).read_bytes()[:65536]
            assert range_value['bytes']==len(expected) and range_value['sha256']==hashlib.sha256(expected).hexdigest()
            command=[str(probe),str(image),str(raw),str(root/'extracted'),path,sid]
            result=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=30)
            assert result.returncode==0,result.stdout+result.stderr
            value=json.loads([line for line in result.stdout.splitlines() if line.startswith('{')][-1])
            payload=Path(value['materialized_path']);manifest=Path(value['manifest_path'])
            assert payload.name==name and payload!=manifest and payload.read_bytes()==(tree/name).read_bytes()
            assert json.loads(manifest.read_text())['source_id']==sid
            stat=payload.stat()
            repeated=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=30)
            assert repeated.returncode==0 and payload.stat().st_mtime_ns==stat.st_mtime_ns
            if name=='History':
                assert any(item['role']=='wal' for item in value['components'])
                from httpserver.services.extractors.sqlite_snapshot import sqlite_snapshot
                with sqlite_snapshot(payload) as (db,coverage):
                    assert db.execute('SELECT note FROM entries').fetchone()[0]=='仅在 WAL 中的中文记录'
                    assert coverage['wal']['committed_frames']>0
                assert not Path(str(payload)+'-shm').exists()
        assert hashlib.sha256(image.read_bytes()).hexdigest()==before
        print('PASS: 原名与清单隔离、初始索引传递、同源 WAL、重复读取不重写、原镜像哈希不变')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analyzer',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True)
    args=parser.parse_args();main(args.analyzer.resolve(),args.probe.resolve())
