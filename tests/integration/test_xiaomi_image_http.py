"""Real task/index/readers/mobile/timeline; model/graph/report use local test doubles."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xiaomi_fixture import build
from httpserver.services import evidence_preflight as preflight


def request(url, body=None):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=120) as response: return response.status, json.load(response)
    except HTTPError as exc: return exc.code, json.load(exc)


def run(binary, root, source=None):
    real = source is not None
    source = source or build(root)
    runtime = root / 'runtime';runtime.mkdir()
    preflight.evidence_inbox = lambda: source.parent.resolve()
    preflight.job_root = lambda: runtime / 'evidence_preflight'
    candidate = next(c for c in preflight.list_candidates() if c['name'] == source.name)
    assert candidate['adapter'] == 'xiaomi-image', candidate
    job = preflight.start_job(candidate['id'], full_hash=True)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        job = preflight.get_job(job['id'])
        if job['status'] not in ('queued','running'): break
        time.sleep(.2)
    assert job['status'] == 'completed' and job['integrity_status'] == 'verified', job
    print('完整预检通过，启动原 HTTP 任务流程', flush=True)
    calls = [];entered = threading.Event();release = threading.Event()
    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, value):
            data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path.startswith('/api/reports/pipeline-tail/status'):
                self.reply({'state':'completed' if release.is_set() else 'running','generation_id':None,'report_id':None,'error_code':None})
            elif self.path.startswith('/v1/models'):self.reply({'data':[{'id':'fixture-model'}]})
            else:self.reply({'status':'COMPLETED','progress':100})
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
            calls.append(self.path)
            if self.path=='/api/reports/pipeline-tail':
                entered.set();self.reply({'state':'running','generation_id':None,'report_id':None,'error_code':None})
            elif self.path.endswith('/chat/completions'):
                assert any('简体中文' in str(m.get('content','')) for m in payload.get('messages',[]) if m.get('role')=='system')
                self.reply({'choices':[{'message':{'content':'SUMMARY: 合成手机样本\nDESCRIPTION: 仅验证调用链，不是案件结论。\nKEYWORDS: 合成,验证'},'finish_reason':'stop'}],'usage':{'total_tokens':20}})
            else:self.reply({'job_id':'fixture-graph','status':'completed'})
    stub=ThreadingHTTPServer(('127.0.0.1',0),Stub);threading.Thread(target=stub.serve_forever,daemon=True).start()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    config={'DATA_DIR':str(runtime),'PROJECT_ROOT':str(Path(__file__).resolve().parents[2]),
        'PYTHON_SERVICE_URL':f'http://127.0.0.1:{stub.server_port}',
        'LLM_BASE_URL':f'http://127.0.0.1:{stub.server_port}','LLM_TEXT_BASE_URL':f'http://127.0.0.1:{stub.server_port}',
        'LLM_MODEL':'fixture-model','LLM_TEXT_MODEL':'fixture-model','LLM_MAX_FILES':'1',
        'GRAPHITI_INGEST_WAIT_TIMEOUT_MIN':'1','GRAPHITI_INGEST_POLL_SECONDS':'1','GRAPHITI_INGEST_RETRIES':'0',
        'REPORT_AUTO_GENERATE_ENABLED':'true','REPORT_TAIL_WAIT_TIMEOUT_MIN':'1','REPORT_TAIL_POLL_SECONDS':'1','REPORT_TAIL_RETRIES':'0',
        'WIN_LINUX_ARTIFACT_LLM_ENABLED':'false'}
    (root/'.env').write_text(''.join(f'{k}={v}\n' for k,v in config.items()))
    with (root/'server.log').open('w') as log:
        server=subprocess.Popen([str(binary),'--http-server',str(port)],cwd=root,env=dict(os.environ,**config),stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                try:
                    if request(base+'/api/health')[0]==200:break
                except OSError:time.sleep(.1)
            else:raise AssertionError('server did not start')
            payload={'image_path':str(source),'android_source':'xiaomi-image','scenarios':['linux'],
                     'platform_analyze':True,'llm_analyze':not real,'filter_profile':'general_forensics'}
            assert request(base+'/api/tasks',payload)[0]==400
            payload.update(preflight_job_id=job['id'],preflight_source_sha256=job['sha256'],preflight_detected_kind='xiaomi_export_image')
            assert request(base+'/api/tasks',{**payload,'platform_analyze':False})[0]==400
            assert request(base+'/api/tasks',{**payload,'db_output_dir':'../outside'})[0]==400
            code,created=request(base+'/api/tasks',payload);assert code==201,(code,created)
            assert created['scenarios']==['android']
            deadline=time.monotonic()+7200;last=0
            while time.monotonic()<deadline:
                _,task=request(base+'/api/tasks/'+created['id'])
                if entered.is_set() and not release.is_set():
                    assert task['status']=='running',task
                    release.set()
                if task['status'] in ('completed','failed','cancelled'):break
                if time.monotonic()-last>30:print(json.dumps(task.get('progress'),ensure_ascii=False),flush=True);last=time.monotonic()
                time.sleep(.2)
            assert task['status']=='completed',task
            assert task['metadata']['device_platform']=='Android / MIUI'
            android=task['metadata']['android_db'];assert android!=task['output_files_db']
            with sqlite3.connect(android) as db:
                counts=dict(db.execute('SELECT kind,COUNT(*) FROM mobile_artifacts GROUP BY kind'))
                assert counts.get('call',0)>0 and counts.get('calendar',0)>0 and counts.get('note',0)>0,counts
                notes=db.execute("SELECT record_json,source_table,source_key,source_db_sha256,timestamp_seconds,related_path FROM mobile_artifacts WHERE kind='note'").fetchall()
                assert all(row[1]=='protobuf:6.2' and len(row[3])==64 and row[4] is None for row in notes)
                if not real:
                    assert counts=={'calendar':1,'call':1,'contact':1,'contact_raw':1,'contact_data':1,'note':1},counts
                    record=json.loads(db.execute("SELECT record_json FROM mobile_artifacts WHERE kind='contact_data'").fetchone()[0])
                    assert record['display_name']=='合成联系人' and record['data1']=='synthetic-number'
                    assert json.loads(notes[0][0])['content']=='合成便签内容' and notes[0][5].endswith('a'*40)
                    assert db.execute("SELECT source_wal_sha256 FROM mobile_artifacts WHERE kind='calendar'").fetchone()[0]
                provenance=db.execute('SELECT COUNT(*) FROM android_filesystem_provenance').fetchone()[0]
                assert provenance>0
            with sqlite3.connect(task['output_raw_db']) as db:
                index_rows=db.execute('SELECT COUNT(*) FROM xiaomi_source_files').fetchone()[0]
                manifest=json.loads(db.execute("SELECT value FROM xiaomi_source_meta WHERE key='manifest'").fetchone()[0])
                assert manifest['source_sha256']==job['sha256']
            with sqlite3.connect(task['output_files_db']) as db:files=db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
            with sqlite3.connect(task['output_events_db']) as db:
                events=db.execute("SELECT COUNT(*) FROM events WHERE event_source='XIAOMI_IMAGE'").fetchone()[0]
                assert events>0
                assert db.execute("SELECT COUNT(*) FROM events WHERE event_source='HARMONY_BACKUP'").fetchone()[0]==0
            path='/data/com.android.providers.contacts/databases/calllog.db' if real else '/storage/emulated/0/DCIM/fixture.txt'
            code,extracted=request(base+'/api/forensics/files/materialize',{'task_id':task['id'],'path':path})
            assert code==200,(code,extracted)
            content=Path(extracted['materialized_path']).read_bytes()
            assert content.startswith(b'SQLite format 3') if real else content=='中文共享存储样本'.encode()
            assert '/api/graphiti/ingest' in calls
            if not real:
                assert entered.is_set() and '/api/reports/pipeline-tail' in calls
                assert any(p.endswith('/chat/completions') for p in calls)
            summary={'task':task,'files':files,'indexed_files':index_rows,'mobile_records':counts,
                'mobile_timeline_events':events,'source_sha256':job['sha256'],
                'live_models_tested':False,'live_graph_tested':False,'graph_stubbed':True,'llm_enabled':not real}
            (root/'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            print(json.dumps({k:v for k,v in summary.items() if k!='task'},ensure_ascii=False),flush=True)
        except Exception:
            log.flush();print((root/'server.log').read_text(errors='replace')[-6000:]);raise
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            stub.shutdown();stub.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analyzer',required=True,type=Path)
    parser.add_argument('--source',type=Path);parser.add_argument('--work',type=Path);args=parser.parse_args()
    if args.work:
        args.work.mkdir(parents=True,exist_ok=False);run(args.analyzer.resolve(),args.work.resolve(),args.source.resolve() if args.source else None)
    else:
        with tempfile.TemporaryDirectory(prefix='xiaomi-http-') as temp:run(args.analyzer.resolve(),Path(temp))
