"""Original HTTP lifecycle with real Windows parsing and canonical local analysis.

Model and graph responses are synthetic. No external intelligence endpoint is used.
"""
import argparse,asyncio,hashlib,json,os,shutil,sqlite3,struct,subprocess,tempfile,threading,zlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from contextlib import asynccontextmanager
from test_task_resume_http import request,free_port,wait_until,wait_status,_healthy,_task,_mark_running
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer
from httpserver.services.case_analysis import cluster_jobs
from httpserver.services.ingestion_job_parts._worker import fetch_pending_cluster_analyses,ingest_pending_cluster_analyses

def run(binary):
    if not shutil.which('mkfs.ext4'):return 77
    with tempfile.TemporaryDirectory(prefix='windows-activity-http-') as folder:
        root=Path(folder);tree=root/'tree';pf=tree/'Windows/Prefetch';logs=tree/'Windows/System32/winevt/Logs';pf.mkdir(parents=True);logs.mkdir(parents=True)
        fixture=Path(__file__).resolve().parents[1]/'fixtures/windows_parser_truth/synthetic_v17.pf'
        shutil.copyfile(fixture,pf/'known.pf')
        header=bytearray(4096);header[:8]=b'ElfFile\0';struct.pack_into('<I',header,32,128);struct.pack_into('<HHHH',header,36,2,3,4096,0);struct.pack_into('<I',header,124,zlib.crc32(header[:120]));(logs/'Empty.evtx').write_bytes(header)
        image=root/'pc.img'
        with image.open('wb') as stream:stream.truncate(64*1024*1024)
        subprocess.run(['mkfs.ext4','-q','-F','-d',str(tree),str(image)],check=True)
        original=hashlib.sha256(image.read_bytes()).hexdigest();base=f'http://127.0.0.1:{free_port()}'
        metrics={'cluster_starts':0,'model_calls':0,'graph_records':0};jobs={}
        class Model:
            async def analyze_event_cluster(self,**kwargs):
                metrics['model_calls']+=1
                return {'analysis':{'summary':'合成模型验证','description':'只验证Windows活动进入原流程及规范记录落库','keywords':['测试']},'model':'local-test-stub'}
        class Graph:
            async def initialize(self):pass
            async def _get_task_graph(self,task_id):return {'ingestor':self}
            @asynccontextmanager
            async def lock_for_group(self,task_id):yield
            async def batch_ingest(self,episodes,group_id):return SimpleNamespace(successful=len(episodes),total_episodes=len(episodes))
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,data,status=200):
                encoded=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
                try:
                    if self.path=='/api/llm/event-cluster-analysis/run':
                        task_id=body['task_id'];task=_task(base,task_id);database=task['output_events_db']
                        assert task['timestamps']['completed'] is None, '运行中的任务不得显示结束时间'
                        with sqlite3.connect(database) as db:
                            assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='PREFETCH_EXECUTION'").fetchone()[0]>0,'活动导入必须早于事件分析'
                        job,_=cluster_jobs.create(database,task_id);metrics['cluster_starts']+=1
                        config=SimpleNamespace(llm_max_event_clusters=100,llm_max_concurrency=1,cluster_analysis_chunk_size=200,llm_context_length=32768,llm_text_max_tokens=1024,llm_text_model='local-test-stub')
                        summary=asyncio.run(ClusterAnalyzer(config,Model(),None).run_analysis(task_id,database,trigger_source='pipeline',ingest=False))
                        assert summary['failed']==0,summary
                        cluster_jobs.update(database,job['job_id'],status='completed',summary={k:v for k,v in summary.items() if k!='results'})
                        self.send({'job_id':job['job_id'],'success':True});return
                    task_id=body.get('task_id')
                    if task_id:
                        task=_task(base,task_id);database=task.get('output_events_db')
                        if database:metrics['graph_records']+=asyncio.run(ingest_pending_cluster_analyses(Graph(),task_id,fetch_pending_cluster_analyses(database),events_db=database))
                    self.send({'job_id':'local-graph-stub','status':'completed'})
                except Exception as exc:self.send({'error':str(exc)},500)
            def do_GET(self):
                if self.path.startswith('/api/llm/event-cluster-analysis/run/'):
                    job_id=self.path.rsplit('/',1)[-1];task_id=cluster_jobs.task_from_job(job_id)
                    self.send(cluster_jobs.read(_task(base,task_id)['output_events_db'],job_id));return
                self.send({'status':'COMPLETED','progress':100,'current_phase':'completed','state':'completed'})
        stub=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=stub.serve_forever,daemon=True).start()
        stub_url=f'http://127.0.0.1:{stub.server_port}';data=root/'data'
        env={**os.environ,'DATA_DIR':str(data),'HTTP_SERVER_PORT':base.rsplit(':',1)[-1],'PYTHON_SERVICE_URL':stub_url,
             'LLM_PYTHON_BASE_URL':stub_url,'LLM_BASE_URL':stub_url,'LLM_TEXT_BASE_URL':stub_url,'LLM_VISION_BASE_URL':stub_url,
             'LLM_API_KEY':'local-test','WIN_LINUX_ARTIFACT_LLM_ENABLED':'false','REPORT_AUTO_GENERATE_ENABLED':'false',
             'GRAPHITI_INGEST_WAIT_TIMEOUT_MIN':'1','EVENT_CLUSTER_WAIT_TIMEOUT_MIN':'2'}
        handle=(root/'server.log').open('w')
        def start():return subprocess.Popen([str(binary),'--http-server'],cwd=root,env=env,stdout=handle,stderr=subprocess.STDOUT)
        server=start()
        try:
            wait_until(lambda:_healthy(base),timeout=90,label='server health')
            code,created=request(base+'/api/tasks',{'image_path':str(image),'scenarios':['windows'],'llm_analyze':False,'llm_event_analyze':True,'platform_analyze':True,'filter_profile':'general_forensics'})
            assert code==201,(code,created);task_id=created['id']
            assert wait_status(base,task_id,('completed','failed'),timeout=180)=='completed',_task(base,task_id)
            task=_task(base,task_id);database=task['output_events_db']
            assert task['timestamps']['completed'] > task['timestamps']['started'], '完成时间必须来自真实结束时刻'
            with sqlite3.connect(database) as db:
                count=db.execute('SELECT COUNT(*) FROM event_cluster_analyses').fetchone()[0]
                assert count>0 and db.execute("SELECT COUNT(*) FROM event_cluster_analyses WHERE trigger_source='pipeline'").fetchone()[0]==count
                assert db.execute('SELECT COUNT(*) FROM event_cluster_members').fetchone()[0]>0
                assert db.execute('SELECT COUNT(*) FROM event_cluster_analyses WHERE ingested_at IS NULL').fetchone()[0]==0
            before=dict(metrics)
            server.terminate();server.wait(timeout=10);_mark_running(data,task_id);server=start()
            wait_until(lambda:_healthy(base),timeout=90,label='restarted health')
            interrupted=_task(base,task_id)
            assert interrupted['timestamps']['completed'] is None and interrupted['timestamps']['interrupted'], '重启中断时间不能冒充完成时间'
            code,_=request(base+f'/api/tasks/{task_id}/resume',{})
            assert code in (200,202),code
            assert wait_status(base,task_id,('completed','failed'),timeout=180)=='completed',_task(base,task_id)
            assert metrics==before,(before,metrics)
            with sqlite3.connect(database) as db:assert db.execute('SELECT COUNT(*) FROM event_cluster_analyses').fetchone()[0]==count
            assert hashlib.sha256(image.read_bytes()).hexdigest()==original
            print(json.dumps({'status':'passed','canonical_records':count,'metrics':metrics,'resume_reused':True,'source_unchanged':True,'live_models_tested':False,'live_graph_tested':False},ensure_ascii=False))
        except Exception:
            handle.flush();print((root/'server.log').read_text(errors='replace')[-12000:]);raise
        finally:
            if server.poll() is None:server.terminate();server.wait(timeout=10)
            handle.close();stub.shutdown();stub.server_close()
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analyzer',type=Path,required=True)
    raise SystemExit(run(parser.parse_args().analyzer.resolve()))
