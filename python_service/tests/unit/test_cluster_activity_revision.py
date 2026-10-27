import asyncio,json,sqlite3
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from httpserver.services.case_analysis.cluster_analyzer import ClusterAnalyzer
from httpserver.services.case_analysis import cluster_jobs,cluster_budget,cluster_revision
from httpserver.services.model_budget import ModelBudgetError

def database(tmp_path):
    path=str(tmp_path/'events.db')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,timestamp INTEGER,event_type TEXT,file_path TEXT,description TEXT,source_id TEXT,system_context TEXT,llm_summary TEXT,llm_description TEXT,llm_keywords TEXT,llm_model_used TEXT,llm_analyzed_at INTEGER,llm_is_relevant INTEGER)')
        conn.execute("INSERT INTO events(id,timestamp,event_type,file_path,description,source_id,system_context) VALUES(1,1700000000,'WINDOWS_EVENT_RECORD','/log.evtx','第一行\n第二行','source-a','原始时间依据')")
    return path

def settings():return SimpleNamespace(llm_max_event_clusters=20,llm_max_concurrency=1,cluster_analysis_chunk_size=200,
    llm_context_length=32768,llm_text_max_tokens=1024,llm_text_model='fake')

class Model:
    async def analyze_event_cluster(self,**kwargs):return {'analysis':{'summary':'合成模型总结','description':'仅测试流程，不作为真实研判'},'model':'fake'}

@pytest.mark.asyncio
async def test_same_ids_with_changed_content_invalidate_and_keep_frozen_members(tmp_path):
    path=database(tmp_path);analyzer=ClusterAnalyzer(settings(),Model(),None)
    first=await analyzer.run_analysis('task',path)
    again=await analyzer.run_analysis('task',path)
    assert first['analyzed']==1 and again['skipped_fresh']==1
    with sqlite3.connect(path) as db:db.execute("UPDATE events SET description='正文改变，ID未变'")
    changed=await analyzer.run_analysis('task',path)
    assert changed['analyzed']==1
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT * FROM event_cluster_analyses ORDER BY id').fetchall()
        assert len(rows)==2 and rows[0]['members_hash']!=rows[1]['members_hash']
        frozen=json.loads(db.execute('SELECT event_json FROM event_cluster_members WHERE analysis_id=1').fetchone()[0])
        assert frozen['description']=='第一行\n第二行'
        assert [r['id'] for r in cluster_revision.filter_current_analyses(db,rows)]==[2]

@pytest.mark.asyncio
async def test_change_while_model_runs_never_persists_stale_result(tmp_path):
    path=database(tmp_path)
    class ChangingModel(Model):
        async def analyze_event_cluster(self,**kwargs):
            with sqlite3.connect(path) as conn:conn.execute("UPDATE events SET description='并发改变'")
            return await super().analyze_event_cluster(**kwargs)
    result=await ClusterAnalyzer(settings(),ChangingModel(),None).run_analysis('task',path)
    assert result['failed']==1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM event_cluster_analyses').fetchone()==(0,)
        assert db.execute('SELECT status FROM cluster_analysis_runs').fetchone()==('partial',)

@pytest.mark.asyncio
async def test_cancellation_closes_durable_analysis_run(tmp_path):
    path=database(tmp_path)
    class CancelledModel(Model):
        async def analyze_event_cluster(self,**kwargs):raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):await ClusterAnalyzer(settings(),CancelledModel(),None).run_analysis('task',path)
    with sqlite3.connect(path) as db:assert db.execute('SELECT status FROM cluster_analysis_runs').fetchone()==('interrupted',)

def test_durable_jobs_survive_cache_loss_and_do_not_duplicate_live_worker(tmp_path):
    path=database(tmp_path)
    job,created=cluster_jobs.create(path,'task');assert created
    same,created=cluster_jobs.create(path,'task');assert not created and same['job_id']==job['job_id']
    cluster_jobs.update(path,job['job_id'],status='completed',summary={'analyzed':1})
    assert cluster_jobs.read(path,job['job_id'])['summary']=={'analyzed':1}
    newer,_=cluster_jobs.create(path,'task')
    with sqlite3.connect(path) as db:db.execute("UPDATE cluster_run_jobs SET owner='99999999:0:gone' WHERE job_id=?",(newer['job_id'],))
    assert cluster_jobs.read(path,newer['job_id'])['status']=='interrupted'
    resumed,created=cluster_jobs.create(path,'task');assert created and resumed['job_id']!=newer['job_id']

def test_cluster_budget_is_atomic_and_resume_does_not_refund(tmp_path):
    path=database(tmp_path);cluster_budget.create(path,'plan',4,400)
    def call(_):
        try:
            with cluster_budget.bind(path,'plan','cluster'):cluster_budget.reserve(60,40)
            return True
        except ModelBudgetError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(call,range(20)))==4
    cluster_budget.create(path,'plan',400,40000)
    assert not call(0)
    with sqlite3.connect(path) as db:assert db.execute('SELECT used_calls,reserved_tokens FROM cluster_model_budget').fetchone()==(4,400)

@pytest.mark.asyncio
async def test_model_configuration_and_task_identity_cannot_reuse_other_derivation(tmp_path):
    path=database(tmp_path);config=settings();analyzer=ClusterAnalyzer(config,Model(),None)
    assert (await analyzer.run_analysis('task',path))['analyzed']==1
    config.llm_text_temperature=0.0
    assert (await analyzer.run_analysis('task',path))['analyzed']==1
    assert (await analyzer.run_analysis('other-task',path))['analyzed']==1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM event_cluster_analyses').fetchone()==(3,)

@pytest.mark.asyncio
async def test_event_dispatch_checks_full_context_before_network(tmp_path):
    import httpx
    from httpserver.services.llm.event_analyzer import EventAnalyzer
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'1. 简要总结\n测试观察\n2. 详细分析\n合成材料\n3. 关键词\n测试'}}]})
    config=settings();config.llm_text_temperature=0.7;config.llm_thinking_body={};config.llm_endpoint='/chat/completions';config.llm_api_key=''
    config.llm_reserved_tokens=512;config.llm_text_base_url='http://test'
    async with httpx.AsyncClient(base_url='http://test',transport=httpx.MockTransport(respond)) as client:
        await EventAnalyzer(config).analyze_event_cluster({'description':'有效材料'},client,temperature=0.0)
        with pytest.raises(ModelBudgetError):await EventAnalyzer(config).analyze_event_cluster({'description':'超长材料'*100000},client)
    assert len(calls)==1 and calls[0]['temperature']==0
