"""Audit checkpoints and atomic per-dispatch budgets, inside reports.db."""
import json,sqlite3,time
from contextlib import closing,contextmanager
from .global_report_models import canonical,digest

class ReportPlanningError(ValueError):
    def __init__(self,message,code='global_report_blocked'):
        self.code=code
        super().__init__(message)

class PlanningStore:
    def __init__(self,database,generation_id,input_hash,budget):
        self.database=str(database);self.generation_id=generation_id;self.input_hash=input_hash;self.budget=budget
        with self.connect() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS report_planning_artifacts(generation_id TEXT,stage TEXT,artifact_key TEXT,input_hash TEXT,payload_json TEXT,payload_hash TEXT,created_at INTEGER,PRIMARY KEY(generation_id,stage,artifact_key));
              CREATE TABLE IF NOT EXISTS report_planning_budget(generation_id TEXT PRIMARY KEY,input_hash TEXT,max_calls INTEGER,max_tokens INTEGER,used_calls INTEGER DEFAULT 0,reserved_tokens INTEGER DEFAULT 0,started_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS report_planning_calls(id INTEGER PRIMARY KEY,generation_id TEXT,stage TEXT,input_bound INTEGER,output_limit INTEGER,created_at INTEGER);
              CREATE TRIGGER IF NOT EXISTS report_planning_no_update BEFORE UPDATE ON report_planning_artifacts BEGIN SELECT RAISE(ABORT,'immutable report planning artifact'); END;
              CREATE TRIGGER IF NOT EXISTS report_planning_no_delete BEFORE DELETE ON report_planning_artifacts BEGIN SELECT RAISE(ABORT,'immutable report planning artifact'); END;
            ''')
            self.authorize(conn)
            conn.execute("INSERT OR IGNORE INTO report_planning_budget(generation_id,input_hash,max_calls,max_tokens,started_at) VALUES(?,?,?,?,strftime('%s','now'))",
                (generation_id,input_hash,budget.max_calls,budget.max_tokens))
    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database,timeout=30)) as conn, conn:
            yield conn
    def authorize(self,conn):
        row=conn.execute('SELECT input_hash,status FROM report_generation_inputs WHERE generation_id=?',(self.generation_id,)).fetchone()
        if not row or row[0]!=self.input_hash or row[1]!='running':raise ReportPlanningError('报告输入身份或运行状态已改变')
    def save(self,stage,key,value):
        encoded=canonical(value);checksum=digest(value)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');self.authorize(conn)
            old=conn.execute('SELECT payload_hash,input_hash FROM report_planning_artifacts WHERE generation_id=? AND stage=? AND artifact_key=?',(self.generation_id,stage,key)).fetchone()
            if old and old!=(checksum,self.input_hash):raise ReportPlanningError('报告中间结果与已冻结版本冲突')
            conn.execute("INSERT OR IGNORE INTO report_planning_artifacts VALUES(?,?,?,?,?,?,strftime('%s','now'))",
                (self.generation_id,stage,key,self.input_hash,encoded,checksum))
        return checksum
    def reserve(self,stage,input_bound,output_limit,stage_call_limit=None):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');self.authorize(conn)
            if stage_call_limit is not None:
                used=conn.execute('SELECT COUNT(*) FROM report_planning_calls WHERE generation_id=? AND stage=?',(self.generation_id,stage)).fetchone()[0]
                if used>=stage_call_limit:raise ReportPlanningError('阶段调用额度已用尽，后续写作与复核额度保留')
            changed=conn.execute("UPDATE report_planning_budget SET used_calls=used_calls+1,reserved_tokens=reserved_tokens+? WHERE generation_id=? AND input_hash=? AND used_calls<max_calls AND reserved_tokens+?<=max_tokens AND strftime('%s','now')-started_at<=?",
                (input_bound+output_limit,self.generation_id,self.input_hash,input_bound+output_limit,self.budget.max_seconds))
            if changed.rowcount!=1:raise ReportPlanningError('报告调用、令牌或时间预算已用尽')
            conn.execute("INSERT INTO report_planning_calls(generation_id,stage,input_bound,output_limit,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(self.generation_id,stage,input_bound,output_limit))
    def usage(self):
        with self.connect() as conn:
            calls,tokens,started=conn.execute('SELECT used_calls,reserved_tokens,started_at FROM report_planning_budget WHERE generation_id=?',(self.generation_id,)).fetchone()
        return {'calls':calls,'reserved_tokens':tokens,'elapsed_seconds':max(0,int(time.time())-started),'accounting':'utf8_byte_bpe_upper_bound'}
    def digests(self):
        with self.connect() as conn:
            return {stage+':'+key:value for stage,key,value in conn.execute('SELECT stage,artifact_key,payload_hash FROM report_planning_artifacts WHERE generation_id=? ORDER BY stage,artifact_key',(self.generation_id,))}

class BudgetedReportProvider:
    def __init__(self,delegate,store,execution_policy=None):
        self.delegate=delegate;self.store=store;self.models=set();self.text_models=set();self.comparison_index=0
        self.execution_policy=execution_policy;self.stage_call_limits={};self.active={};self.peak={}
        self.retry_rate_limits=False
    def bound(self,system,payload):
        return len(canonical([{'role':'system','content':system},{'role':'user','content':canonical(payload)}]).encode())+self.store.budget.reserved_tokens
    def fits(self,system,payload,output=None):return self.bound(system,payload)+(output or self.output_limit)<=self.store.budget.context_limit
    @property
    def output_limit(self):return min(self.store.budget.output_tokens,(self.store.budget.context_limit-self.store.budget.reserved_tokens)//3)
    async def call(self,stage,key,system,payload,output=None):
        import asyncio
        output=output or self.output_limit;bound=self.bound(system,payload)
        if bound+output>self.store.budget.context_limit:raise ReportPlanningError('完整报告请求超出上下文预算')
        request={'system':system,'input':payload,'output_limit':output,'input_bound':bound}
        if self.execution_policy is not None:
            return await self._concurrent_call(stage,key,request)
        self.store.save('request',stage+':'+key,request)
        self.store.reserve(stage,bound,output)
        remaining=max(1,self.store.budget.max_seconds-self.store.usage()['elapsed_seconds'])
        response=await asyncio.wait_for(self.delegate.chat_completion(system,canonical(payload),max_tokens=output,temperature=0.0),timeout=remaining)
        self.store.save('response',stage+':'+key,response)
        if response.get('model'):self.models.add(response['model']);self.text_models.add(response['model'])
        if response.get('finish_reason')=='length':raise ReportPlanningError('报告模型输出被截断，未并入正文')
        content=response.get('content')
        if not isinstance(content,str) or len(content)>100000:raise ReportPlanningError('报告模型返回内容无效或超限')
        from .generation_structured import _loads_strict
        return _loads_strict(content)

    async def _concurrent_call(self,stage,key,request):
        import asyncio
        import httpx
        from .report_transport import report_cooldown,retry_delay
        from .global_report_concurrency import report_request_slots
        from .generation_structured import _loads_strict
        started=time.monotonic()
        remaining=self.store.budget.max_seconds-self.store.usage()['elapsed_seconds']
        if remaining<=0:raise ReportPlanningError('报告时间预算已用尽')
        async def invoke():
            cooldown=report_cooldown() if self.retry_rate_limits else None
            for attempt in range(3 if cooldown else 1):
                if cooldown:await cooldown.wait()
                async with report_request_slots():
                    if cooldown:await cooldown.wait()
                    attempt_key=stage+':'+key+(f':http-retry-{attempt}' if attempt else '')
                    await asyncio.to_thread(self.store.save,'request',attempt_key,request)
                    # Every dispatched attempt is charged, including a 429.
                    await asyncio.to_thread(self.store.reserve,stage,request['input_bound'],request['output_limit'],self.stage_call_limits.get(stage))
                    self.active[stage]=self.active.get(stage,0)+1;self.peak[stage]=max(self.peak.get(stage,0),self.active[stage])
                    try:
                        response=await self.delegate.chat_completion(request['system'],canonical(request['input']),max_tokens=request['output_limit'],temperature=0.0)
                    except httpx.HTTPStatusError as error:
                        if not cooldown or error.response.status_code!=429 or attempt==2:raise
                        delay=retry_delay(error.response,attempt);cooldown.defer(delay)
                        await asyncio.to_thread(self.store.save,'transport_retry',attempt_key,
                            {'status':429,'attempt':attempt+1,'cooldown_seconds':delay,'reason':'模型限流，等待后按原请求重试；失败调用仍占预算'})
                        continue
                    finally:self.active[stage]-=1
                    await asyncio.to_thread(self.store.save,'response',stage+':'+key,response)
                    await asyncio.to_thread(self.store.save,'call_timing',stage+':'+key,{'elapsed_seconds':round(time.monotonic()-started,6)})
                    if response.get('model'):self.models.add(response['model']);self.text_models.add(response['model'])
                    if response.get('finish_reason')=='length':raise ReportPlanningError('报告模型输出被截断，未并入正文')
                    content=response.get('content')
                    if not isinstance(content,str) or len(content)>100000:raise ReportPlanningError('报告模型返回内容无效或超限')
                    return _loads_strict(content)
        return await asyncio.wait_for(invoke(),timeout=remaining)
    async def chat_completion(self,system,user,max_tokens=None,**kwargs):
        key=str(self.comparison_index);self.comparison_index+=1
        value=await self.call('comparison',key,system,json.loads(user),output=min(max_tokens or self.output_limit,self.output_limit))
        return {'content':canonical(value),'model':', '.join(sorted(self.models))}
