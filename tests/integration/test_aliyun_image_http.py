"""Cloud export -> existing Task -> files/events/extraction and original report gate.

Only model/graph responses are local test doubles. The task, preflight,
decompression, filesystem, Linux parsers and file materialization are real.
"""
import argparse
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from httpserver.services import evidence_preflight as preflight


LINE = '127.0.0.1 - - [23/Oct/2026:12:00:00 +0800] "GET /fixture HTTP/1.1" 200 12 "-" "fixture"\n'
PANEL_LINE = json.dumps(['2026-10-23 12:00:00','127.0.0.1:12345','GET','/fixture?','fixture-agent','{}',10,200,12,'extra','extra','test'])+'\n'


def request(url, body=None):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response: return response.status, json.load(response)
    except HTTPError as error: return error.code, json.load(error)


def fixture(root):
    tree = root / 'tree'
    for name, value in {
        'etc/os-release': 'NAME="Alibaba Cloud Linux"\nID=alinux\n',
        'etc/passwd': 'root:x:0:0:root:/root:/bin/bash\n',
        'var/log/nginx/access.log': LINE,
        'www/wwwlogs/fixture.log': LINE * 2,
        'www/server/panel/vhost/nginx/fixture.conf': 'server { listen 80; server_name fixture.local; root /opt/site; }\n',
        'www/wwwlogs/request/2026-10-23.json': PANEL_LINE * 2,
        'www/server/panel/logs/request/2026-10-23.json': PANEL_LINE * 2,
    }.items():
        path = tree / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
    raw = root / 'system.raw'
    with raw.open('wb') as stream: stream.truncate(64 * 1024**2)
    subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-d', str(tree), str(raw)], check=True)
    source = root / 'file_m-测试_system.raw.tar.gz'
    with tarfile.open(source, 'w:gz') as archive: archive.add(raw, arcname='file_m-test_system.raw')
    return source


def wait_preflight(source, runtime):
    preflight.evidence_inbox = lambda: source.parent.resolve()
    preflight.job_root = lambda: runtime / 'evidence_preflight'
    candidate = next(c for c in preflight.list_candidates() if c['name'] == source.name)
    assert candidate['adapter'] == 'aliyun-image', candidate
    job = preflight.start_job(candidate['id'], full_hash=True)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        job = preflight.get_job(job['id'])
        if job['status'] not in {'queued','running'}: break
        time.sleep(.1)
    assert job['status'] == 'completed' and job['integrity_status'] == 'verified', job
    return job


def run(binary, root, source=None):
    real = source is not None
    source = source or fixture(root)
    runtime = root / 'runtime'; runtime.mkdir()
    job = wait_preflight(source, runtime)
    print('预检通过，开始原有 HTTP 任务流程', flush=True)
    calls = []
    report_entered, report_release = threading.Event(), threading.Event()
    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, body):
            data=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path.startswith('/api/graphiti/jobs/'):
                self.reply({'status':'COMPLETED','progress':100,'error':None})
            elif self.path.startswith('/api/reports/pipeline-tail/status'):
                self.reply({'state':'completed' if report_release.is_set() else 'running',
                            'generation_id':None,'report_id':None,'error_code':None})
            elif self.path.startswith('/v1/models'):
                self.reply({'data':[{'id':'synthetic-local-model'}]})
            else: self.reply({'status':'healthy'})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
            calls.append(self.path)  # Never save actual evidence text in the test transcript.
            if self.path == '/api/graphiti/ingest': self.reply({'job_id':'synthetic-job','status':'pending'})
            elif self.path == '/api/reports/pipeline-tail':
                report_entered.set();self.reply({'state':'running','generation_id':None,'report_id':None,'error_code':None})
            elif self.path.endswith('/chat/completions'):
                assert any('简体中文' in str(m.get('content','')) for m in body.get('messages',[]) if m.get('role')=='system')
                self.reply({'choices':[{'message':{'content':'SUMMARY: 合成验证摘要\nDESCRIPTION: 仅验证调用链，不是实际案件结论。\nKEYWORDS: 合成,验证'},'finish_reason':'stop'}], 'usage':{'total_tokens':20}})
            else: self.reply({'success':True,'status':'completed'})
    stub=ThreadingHTTPServer(('127.0.0.1',0),Stub)
    threading.Thread(target=stub.serve_forever,daemon=True).start()
    with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env=dict(os.environ,DATA_DIR=str(runtime),PROJECT_ROOT=str(Path(__file__).resolve().parents[2]),PYTHON_SERVICE_URL=f'http://127.0.0.1:{stub.server_port}',
        LLM_BASE_URL=f'http://127.0.0.1:{stub.server_port}', LLM_TEXT_BASE_URL=f'http://127.0.0.1:{stub.server_port}',
        LLM_TEXT_MODEL='synthetic-local-model', LLM_MODEL='synthetic-local-model', LLM_MAX_FILES='1',
        GRAPHITI_INGEST_WAIT_TIMEOUT_MIN='1', GRAPHITI_INGEST_POLL_SECONDS='1', GRAPHITI_INGEST_RETRIES='0',
        REPORT_AUTO_GENERATE_ENABLED='true',REPORT_TAIL_WAIT_TIMEOUT_MIN='1',REPORT_TAIL_POLL_SECONDS='1',REPORT_TAIL_RETRIES='0',
        WIN_LINUX_ARTIFACT_LLM_ENABLED='false')
    test_keys = ('DATA_DIR','PROJECT_ROOT','PYTHON_SERVICE_URL','LLM_BASE_URL','LLM_TEXT_BASE_URL',
        'LLM_TEXT_MODEL','LLM_MODEL','LLM_MAX_FILES','GRAPHITI_INGEST_WAIT_TIMEOUT_MIN',
        'GRAPHITI_INGEST_POLL_SECONDS','GRAPHITI_INGEST_RETRIES','REPORT_AUTO_GENERATE_ENABLED',
        'REPORT_TAIL_WAIT_TIMEOUT_MIN','REPORT_TAIL_POLL_SECONDS','REPORT_TAIL_RETRIES','WIN_LINUX_ARTIFACT_LLM_ENABLED')
    # An explicit isolated config prevents inherited workstation settings from
    # redirecting any evidence/model request outside the local test responder.
    (root/'.env').write_text(''.join(f'{key}={env[key]}\n' for key in test_keys))
    with (root/'server.log').open('w') as log:
        server=subprocess.Popen([str(binary),'--http-server',str(port)],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                try:
                    if request(base+'/api/health')[0]==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('server did not start')
            payload={'image_path':str(source),'android_source':'aliyun-image','scenarios':['android'],
                     'platform_analyze':True,'llm_analyze':not real,'filter_profile':'general_forensics'}
            assert request(base+'/api/tasks',payload)[0]==400
            payload.update(preflight_job_id=job['id'],preflight_source_sha256=job['sha256'],preflight_detected_kind=job['detected']['kind'])
            status,created=request(base+'/api/tasks',payload)
            assert status==201,(status,created)
            assert created['scenarios']==['linux']
            task_id=created['id']
            deadline=time.monotonic()+1800
            last=0
            while time.monotonic()<deadline:
                _,task=request(base+'/api/tasks/'+task_id)
                if not real and report_entered.is_set() and not report_release.is_set():
                    assert task['status']=='running',task
                    report_release.set()
                if task['status'] in ('completed','failed','cancelled'):break
                if time.monotonic()-last>30:
                    print(json.dumps({'status':task['status'],'progress':task.get('progress')},ensure_ascii=False),flush=True);last=time.monotonic()
                time.sleep(.2)
            assert task['status']=='completed',task
            assert task['android_source']=='aliyun-image' and task['scenarios']==['linux']
            assert task['metadata']['aliyun_original_source']==str(source)
            assert task['metadata']['aliyun_prepared']=='true'
            assert Path(task['image_path']).name=='system.raw'
            manifest=json.loads(Path(task['metadata']['aliyun_manifest_path']).read_text())
            assert manifest['source_sha256']==job['sha256'] and manifest['gzip_crc_verified']
            assert hashlib.sha256(Path(task['metadata']['aliyun_manifest_path']).read_bytes()).hexdigest()==task['metadata']['aliyun_manifest_sha256']
            with sqlite3.connect(task['output_files_db']) as db:
                files=db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
            with sqlite3.connect(task['scenario_databases']['linux']) as db:
                logs=db.execute('SELECT COUNT(*) FROM linux_nginx_access_logs').fetchone()[0]
                configs=db.execute('SELECT COUNT(*) FROM linux_nginx_server_blocks').fetchone()[0]
                panel=db.execute('SELECT COUNT(*) FROM linux_panel_requests').fetchone()[0]
                assert files>0 and configs>0 and panel>0
                assert db.execute("SELECT COUNT(*) FROM linux_panel_requests WHERE source_line>0 AND source_inode>0 AND length(source_sha256)=64 AND timestamp_raw<>''").fetchone()[0]==panel
                if not real:
                    assert logs==3,logs
                    assert panel==2
                    assert db.execute('SELECT COUNT(*) FROM linux_panel_request_sources').fetchone()[0]==2
                    assert db.execute('SELECT COUNT(DISTINCT canonical_source) FROM linux_panel_request_sources').fetchone()[0]==1
                    assert db.execute("SELECT source_line FROM linux_nginx_access_logs WHERE source_file='/www/wwwlogs/fixture.log' ORDER BY source_line").fetchall()==[(1,),(2,)]
            with sqlite3.connect(task['output_events_db']) as db:
                nginx_events=db.execute("SELECT COUNT(*) FROM events WHERE event_type='NGINX_ACCESS'").fetchone()[0]
                assert nginx_events==logs
            status,materialized=request(base+'/api/forensics/files/materialize',{'task_id':task_id,'path':'/etc/os-release'})
            assert status==200,(status,materialized)
            assert 'Alibaba Cloud Linux' in Path(materialized['materialized_path']).read_text()
            assert '/api/graphiti/ingest' in calls
            if not real:
                assert report_entered.is_set() and '/api/reports/pipeline-tail' in calls
                assert any(path.endswith('/chat/completions') for path in calls)
            summary={'task_id':task_id,'files':files,'nginx_access_records':logs,'nginx_configs':configs,'panel_request_records':panel,
                     'nginx_timeline_events':nginx_events,'model_stub':not real,'live_models_tested':False,
                     'source_sha256':job['sha256'],'raw_sha256':manifest['raw_sha256'],
                     'source_manifest':task['metadata']['aliyun_manifest_path'],'task':task}
            (root/'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            print(json.dumps({k:v for k,v in summary.items() if k!='task'},ensure_ascii=False),flush=True)
            if not real:
                # An existing pre-provenance table must migrate without losing rows.
                legacy = root/'legacy-cli'; legacy.mkdir()
                with sqlite3.connect(legacy/'system_files.db') as db:
                    db.execute('CREATE TABLE linux_nginx_access_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, remote_ip TEXT, method TEXT, url TEXT, status_code INTEGER, response_size INTEGER, referer TEXT, user_agent TEXT, request_time REAL, upstream_addr TEXT)')
                    db.execute("INSERT INTO linux_nginx_access_logs(timestamp,url) VALUES(0,'/existing-row')")
                with (root/'legacy-cli.log').open('w') as legacy_log:
                    cli = subprocess.run([str(binary),task['image_path'],'--linux-analyze','--no-ai','--db-dir',str(legacy)],
                        cwd=root,env=env,stdout=legacy_log,stderr=subprocess.STDOUT,timeout=90)
                assert cli.returncode==0
                with sqlite3.connect(legacy/'system_files.db') as db:
                    assert db.execute("SELECT COUNT(*) FROM linux_nginx_access_logs WHERE url='/existing-row'").fetchone()[0]==1
                    assert db.execute("SELECT COUNT(*) FROM linux_nginx_access_logs WHERE source_line>0").fetchone()[0]==3
                damaged=root/'damaged.raw.tar.gz'; damaged.write_bytes(source.read_bytes())
                bad_job=wait_preflight(damaged,runtime)
                damaged.write_bytes(damaged.read_bytes()+b'changed')
                rejected={**payload,'image_path':str(damaged),'preflight_job_id':bad_job['id'],'preflight_source_sha256':bad_job['sha256']}
                assert request(base+'/api/tasks',rejected)[0]==409
                corrupted=root/'crc.raw.tar.gz';data=bytearray(source.read_bytes());data[-8]^=1;corrupted.write_bytes(data)
                bad_job=wait_preflight(corrupted,runtime)
                rejected.update(image_path=str(corrupted),preflight_job_id=bad_job['id'],preflight_source_sha256=bad_job['sha256'],llm_analyze=False)
                status,failed=request(base+'/api/tasks',rejected);assert status==201
                for _ in range(300):
                    failed=request(base+'/api/tasks/'+failed['id'])[1]
                    if failed['status']=='failed':break
                    time.sleep(.1)
                assert failed['status']=='failed' and failed['metadata'].get('aliyun_prepared')!='true',failed
        except Exception:
            log.flush();print((root/'server.log').read_text(errors='replace')[-4000:]);raise
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            stub.shutdown();stub.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analyzer',type=Path,required=True)
    parser.add_argument('--source',type=Path);parser.add_argument('--work',type=Path)
    args=parser.parse_args()
    if args.work:
        args.work.mkdir(parents=True,exist_ok=False)
        run(args.analyzer.resolve(),args.work.resolve(),args.source.resolve() if args.source else None)
    else:
        with tempfile.TemporaryDirectory(prefix='aliyun-http-') as temp:run(args.analyzer.resolve(),Path(temp))
