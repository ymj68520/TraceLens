import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from httpserver.services.model_budget import prepare_text_request,serialized_bound,ModelBudgetError,analysis_budget,reserve_attempt

def settings(**kwargs):return SimpleNamespace(llm_context_length=4096,llm_text_max_tokens=2048,llm_reserved_tokens=512,**kwargs)

def test_final_request_includes_instruction_and_never_duplicates_original_body():
    original='原始材料甲乙丙丁\n'*20000
    messages,output,admission=prepare_text_request(settings(),'你是取证分析员',original,'调查要求\n'+original)
    assert serialized_bound(messages)+output+512<=4096
    assert messages[1]['content'].count('原始材料')<1000
    assert admission['content_truncated']
    assert '正文见本次请求的材料部分' in messages[1]['content']

def test_oversized_instructions_fail_before_dispatch():
    with pytest.raises(ModelBudgetError,match='未发送'):
        prepare_text_request(settings(),'系统','材料','超长要求'*10000)

@pytest.mark.parametrize('size',[0,1,99,1000,90000])
def test_unicode_budget_checks_complete_message(size):
    messages,output,_=prepare_text_request(settings(),'系统说明','中文😀"\\\n'*size)
    assert serialized_bound(messages)+output+512<=4096
    json.dumps(messages,ensure_ascii=False).encode('utf-8').decode('utf-8')

def test_output_maximum_is_capped_to_leave_a_valid_input_window():
    messages,output,_=prepare_text_request(settings(),'系统','内容',max_tokens=8192)
    assert output<4096 and serialized_bound(messages)+output+512<=4096

def test_atomic_attempt_budget_survives_parallel_workers_and_reentry(tmp_path):
    database=str(tmp_path/'files.db')
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE selection_runs(plan_id TEXT,plan_json TEXT,created_at INTEGER);'
            'CREATE TABLE selection_budget(plan_id TEXT,max_calls INTEGER,max_tokens INTEGER,used_calls INTEGER DEFAULT 0,reserved_tokens INTEGER DEFAULT 0);'
            'CREATE TABLE selection_call_ledger(id INTEGER PRIMARY KEY,plan_id TEXT,source_key TEXT,input_bound INTEGER,output_limit INTEGER,created_at INTEGER);')
        db.execute('INSERT INTO selection_runs VALUES(?,?,1)',('p',json.dumps({'selected':[{'task_id':'t','reference':'source','source_key':'t:source'}]})))
        db.execute('INSERT INTO selection_budget(plan_id,max_calls,max_tokens) VALUES(?,?,?)',('p',5,500))
    def worker(_):
        try:
            with analysis_budget(database,'source',task_id='t'):reserve_attempt(60,40)
            return True
        except ModelBudgetError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(worker,range(20)))==5
    assert worker(1) is False
    with sqlite3.connect(database) as db:assert db.execute('SELECT used_calls,reserved_tokens FROM selection_budget').fetchone()==(5,500)

@pytest.mark.asyncio
async def test_bom_utf16_text_is_readable_for_probing_and_formal_analysis(tmp_path):
    from httpserver.services.extractors.text_dump import TextDumpExtractor
    file=tmp_path/'公告.txt';file.write_bytes('用户原始中文记录'.encode('utf-16'))
    parsed=await TextDumpExtractor().extract_result(str(file))
    assert parsed.text=='用户原始中文记录' and parsed.status=='ok'


@pytest.mark.asyncio
async def test_actual_text_request_preserves_zero_temperature_and_budget():
    import httpx
    from httpserver.services.llm.file_analyzer import FileAnalyzer
    captured=[]
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'1. 简要总结\n已识别记录\n2. 详细分析\n包含合成材料\n3. 关键词\n测试\n4. 取证价值\n低'}}], 'usage':{'total_tokens':20}})
    config=settings(llm_text_model='test',llm_text_temperature=0.7,llm_text_base_url='http://test',llm_endpoint='/chat/completions',llm_thinking_body={},llm_api_key='')
    async with httpx.AsyncClient(base_url='http://test',transport=httpx.MockTransport(respond)) as client:
        result=await FileAnalyzer(config).analyze_file('测试正文'*10000,client,None,temperature=0.0)
    assert result['analysis']['description'] and len(captured)==1
    assert captured[0]['temperature']==0.0
    assert serialized_bound(captured[0]['messages'])+captured[0]['max_tokens']+512<=4096


def _plan_database(tmp_path):
    import hashlib
    database=str(tmp_path/'plans.db')
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE selection_runs(plan_id TEXT PRIMARY KEY,plan_json TEXT,created_at INTEGER);'
            'CREATE TABLE selection_budget(plan_id TEXT PRIMARY KEY,max_calls INTEGER,max_tokens INTEGER,used_calls INTEGER DEFAULT 0,reserved_tokens INTEGER DEFAULT 0);'
            'CREATE TABLE selection_call_ledger(id INTEGER PRIMARY KEY,plan_id TEXT,source_key TEXT,input_bound INTEGER,output_limit INTEGER,created_at INTEGER);'
            'CREATE TABLE selection_execution(plan_id TEXT,source_key TEXT,state TEXT,updated_at INTEGER,error TEXT,PRIMARY KEY(plan_id,source_key));')
        for index,key in enumerate(('original','newer')):
            plan={'policy_version':'candidate-selection:v3','plan_id':key,
                  'selected':[{'task_id':'task','reference':'source','source_key':'task:source'}]}
            plan['plan_digest']=hashlib.sha256(json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            db.execute('INSERT INTO selection_runs VALUES(?,?,?)',(key,json.dumps(plan),index))
            db.execute('INSERT INTO selection_budget(plan_id,max_calls,max_tokens) VALUES(?,?,?)',(key,3,300))
    return database


def test_exact_active_plan_survives_newer_plan_and_restores_outer_scope(tmp_path):
    from httpserver.services.model_budget import selection_run,current_selection_run,mark_finished,plan_allows_cached_analysis
    database=_plan_database(tmp_path)
    with selection_run('original'):
        with analysis_budget(database,'source',task_id='task') as scope:
            assert scope[1]=='original'
            reserve_attempt(60,40);mark_finished(database,'source')
        assert plan_allows_cached_analysis(database,'source',task_id='task')
        with selection_run('newer'):
            assert not plan_allows_cached_analysis(database,'source',task_id='task')
        assert current_selection_run()=='original'
    assert current_selection_run() is None
    with sqlite3.connect(database) as db:
        assert dict(db.execute('SELECT plan_id,used_calls FROM selection_budget'))=={'original':1,'newer':0}


@pytest.mark.parametrize('mode',['modified_digest','wrong_source','wrong_task','missing_plan'])
def test_invalid_plan_binding_stops_before_call_reservation(tmp_path,mode):
    database=_plan_database(tmp_path)
    if mode=='modified_digest':
        with sqlite3.connect(database) as db:
            raw=json.loads(db.execute("SELECT plan_json FROM selection_runs WHERE plan_id='original'").fetchone()[0])
            raw['selected'][0]['path']='changed'
            db.execute("UPDATE selection_runs SET plan_json=? WHERE plan_id='original'",(json.dumps(raw),))
    with pytest.raises(ModelBudgetError):
        with analysis_budget(database,'other' if mode=='wrong_source' else 'source',
                             'absent' if mode=='missing_plan' else 'original',
                             'other' if mode=='wrong_task' else 'task'):
            reserve_attempt(60,40)
    with sqlite3.connect(database) as db:assert db.execute('SELECT SUM(used_calls) FROM selection_budget').fetchone()==(0,)


def test_vision_requires_bound_and_cannot_bypass_shared_run_budget(tmp_path):
    from httpserver.services.model_budget import reserve_vision_attempt
    database=_plan_database(tmp_path)
    with analysis_budget(database,'source','original','task'):
        with pytest.raises(ModelBudgetError,match='未配置'):reserve_vision_attempt(settings(),'图片描述',1)
        with pytest.raises(ModelBudgetError,match='上下文'):reserve_vision_attempt(settings(llm_vision_image_token_bound=5000),'图片描述',1)
        # A valid per-request window is still refused when the run cap is lower.
        with pytest.raises(ModelBudgetError,match='本轮'):reserve_vision_attempt(settings(llm_vision_image_token_bound=100),'图片描述',1)
    with sqlite3.connect(database) as db:assert db.execute('SELECT SUM(used_calls) FROM selection_budget').fetchone()==(0,)


@pytest.mark.asyncio
async def test_case_descriptions_keep_outer_plan_and_bind_direct_entry(monkeypatch):
    from unittest.mock import AsyncMock
    from httpserver.services.model_budget import selection_run,current_selection_run
    from httpserver.services import selection_binding
    from httpserver.services.case_analysis.case_analysis_parts._core import CaseAnalysisCoreMixin
    async def analyze(*args,**kwargs):return [{'plan':current_selection_run(),'paths':args[1]}]
    service=CaseAnalysisCoreMixin()
    service._file_analyzer=SimpleNamespace(analyze_files=analyze)
    service._cpp_backend=SimpleNamespace(selection_plan=AsyncMock())
    binder=AsyncMock(return_value=({'plan_id':'explicit'},['selected'],[{'selection_state':'deferred'}]))
    monkeypatch.setattr(selection_binding,'bind_sources',binder)
    with selection_run('pipeline'):
        result=await service.generate_file_descriptions('db',['source'],'案情',task_id='task')
        assert result==[{'plan':'pipeline','paths':['source']}]
        binder.assert_not_awaited()
    result=await service.generate_file_descriptions('db',['source'],'案情',task_id='task')
    assert result==[{'plan':'explicit','paths':['selected']},{'selection_state':'deferred'}]
    assert current_selection_run() is None
    binder.assert_awaited_once_with(service._cpp_backend,'task',['source'],'案情')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['audio','video'])
async def test_media_routes_bind_selected_plan_before_analyzer(tmp_path,monkeypatch,kind):
    from contextlib import asynccontextmanager
    from importlib import import_module
    from fastapi import HTTPException
    from httpserver.services import task_store,source_reading
    from httpserver.services.model_budget import reserve_attempt
    module=import_module('httpserver.routes.'+kind+'_analysis')
    database=_plan_database(tmp_path)
    async def task_record(_):return {'output_files_db':database}
    @asynccontextmanager
    async def source_file(*args,**kwargs):yield '/private/readonly-copy','source',{}
    async def analyze(request,validated=False):
        assert validated and request.file_path=='/private/readonly-copy'
        reserve_attempt(60,40)
        return {'success':True}
    monkeypatch.setattr(task_store,'get_task_record',task_record)
    monkeypatch.setattr(source_reading,'task_source_file',source_file)
    monkeypatch.setattr(module,'_analyze_media_copy',analyze)
    request_type=module.AudioTranscribeRequest if kind=='audio' else module.VideoDescribeRequest
    handler=module.transcribe_audio if kind=='audio' else module.describe_video
    request=request_type(task_id='task',file_path='source',selection_plan_id='original')
    assert await handler(request)=={'success':True}
    with pytest.raises(HTTPException) as exc:
        await handler(request.model_copy(update={'selection_plan_id':'missing'}))
    assert exc.value.status_code==422
    with sqlite3.connect(database) as db:
        assert dict(db.execute('SELECT plan_id,used_calls FROM selection_budget'))=={'original':1,'newer':0}
