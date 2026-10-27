import asyncio,hashlib,json,sqlite3,time
import pytest
from test_global_report import envelope,admitted,Model
from httpserver.services.forensic_report.models import ReportGenerationEnvelopeV9,GenerationReportManifest,parse_generation_envelope
from httpserver.services.forensic_report.global_report_models import ReportExecutionPolicy
from httpserver.services.forensic_report.global_report_concurrency import ordered_pool
from httpserver.services.forensic_report.global_report_concurrency import attach_source_records
from httpserver.services.forensic_report.global_report_store import PlanningStore,ReportPlanningError
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.investigation.acquisition import canonical_json

def input9(count=30,serial=False,**budgets):
    raw=envelope(count,**budgets).model_dump(mode='json')
    raw.update(schema_version=9,prompt_version='final-report:evidence-only:v4',
        execution_policy=ReportExecutionPolicy(extraction_concurrency=1 if serial else 4,writing_concurrency=1 if serial else 2,review_concurrency=1 if serial else 2).model_dump(mode='json'))
    return ReportGenerationEnvelopeV9.model_validate(raw)

def test_context_packet_preserves_machine_visual_kind_and_source_limitations():
    material=envelope(1).neutral_materials[0].model_copy(update={'kind':'machine_visual','limitations':('机器视觉观察不是逐字原文',)})
    request=attach_source_records({'allowed_citation_ids':['c0001']},{material.material_id:material},{material.material_id:'c0001'})
    assert request['source_records'][0]['kind']=='machine_visual'
    assert request['source_records'][0]['limitations']==material.limitations
    assert '不是原文' in request['source_record_policy']

class TimedModel(Model):
    def __init__(self,delay=.015,saturation=None):
        super().__init__();self.active={};self.peak={};self.delay=delay;self.contexts=[]
        self.gates={stage:(asyncio.Event(),count) for stage,count in (saturation or {}).items()}
    async def chat_completion(self,system,prompt,**kwargs):
        payload=json.loads(prompt)
        for record in payload.get('source_records',[]):
            assert hashlib.sha256(record['text'].encode()).hexdigest()==record['content_sha256']
            assert record['character_start']==0 and record['character_end']==len(record['text'])
        stage='extraction' if 'windows' in payload else payload.get('operation','chapter')
        self.active[stage]=self.active.get(stage,0)+1
        self.peak[stage]=max(self.peak.get(stage,0),self.active[stage])
        try:
            if stage in self.gates:
                gate,count=self.gates[stage]
                if self.active[stage]>=count:gate.set()
                await asyncio.wait_for(gate.wait(),timeout=5)
            await asyncio.sleep(self.delay)
            if payload.get('operation')=='coherence_review':
                return {'content':json.dumps({'issues':[]}), 'model':'test-model','finish_reason':'stop'}
            if payload.get('completed_body'):
                self.contexts.append(payload)
                assert all(row['content'] for row in payload['completed_body'])
            if 'required_claim_ids' in payload:
                payload['claims']=[c for c in payload['claims'] if c['claim_id'] in payload['required_claim_ids']]
                prompt=json.dumps(payload,ensure_ascii=False)
            return await super().chat_completion(system,prompt,**kwargs)
        finally:self.active[stage]-=1

async def execute(root,value,model):
    repo,row=admitted(root,value);writer=GenerationReportWriter(root)
    await ReportGenerationExecutor(repo,writer,model)._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='completed',done.error_message
    return GenerationReportManifest.model_validate(writer.read_manifest('task',done.report_id)),repo,row

@pytest.mark.asyncio
async def test_original_executor_uses_4_2_2_then_closes_over_final_body(tmp_path):
    model=TimedModel(saturation={'extraction':4,'chapter':2,'semantic_review':2});value=input9()
    report,repo,row=await execute(tmp_path,value,model)
    assert report.schema_version=='1.4'
    assert model.peak['extraction']==4 and model.peak['chapter']==2 and model.peak['semantic_review']==2
    assert model.contexts and report.organization.validation['coherence_status']=='auxiliary_checks_passed'
    assert all(value==0 for value in model.active.values())
    closing={c.section_id for c in report.organization.plan.chapters if c.role in ('scope','conclusion')}
    assert closing<=set(p['section_id'] for p in model.contexts)
    expected=[{'section_id':c.section_id,'heading':s.heading,'content':s.content} for c,s in zip(report.organization.plan.chapters,report.sections) if c.role not in ('scope','conclusion')]
    assert model.contexts[-1]['completed_body']==expected
    assert parse_generation_envelope(canonical_json(value))==value
    with sqlite3.connect(repo.db_path) as db:
        calls=db.execute('SELECT COUNT(*) FROM report_planning_calls WHERE generation_id=?',(row.generation_id,)).fetchone()[0]
        assert calls<=value.report_budget.max_calls

@pytest.mark.asyncio
async def test_serial_and_parallel_use_same_call_set_findings_and_plan(tmp_path):
    outputs=[]
    for serial in (True,False):
        root=tmp_path/str(serial);root.mkdir();model=TimedModel()
        report,repo,row=await execute(root,input9(serial=serial,max_calls=72),model)
        with sqlite3.connect(repo.db_path) as db:
            requests=[(key,json.loads(value)) for key,value in db.execute("SELECT artifact_key,payload_json FROM report_planning_artifacts WHERE generation_id=? AND stage='request' ORDER BY artifact_key",(row.generation_id,))]
        outputs.append((report,requests))
    first,second=outputs
    assert first[1]==second[1]
    assert first[0].sections==second[0].sections
    assert first[0].organization.findings==second[0].organization.findings
    assert first[0].organization.coverage==second[0].organization.coverage
    assert first[0].organization.plan==second[0].organization.plan

@pytest.mark.asyncio
async def test_worker_failure_cancels_and_drains_inflight_siblings():
    live=set()
    async def operation(index):
        live.add(index)
        try:
            if index==1:
                await asyncio.sleep(.01);raise ValueError('stop')
            await asyncio.sleep(10)
        finally:live.remove(index)
    with pytest.raises(ValueError):await ordered_pool(range(100),4,operation)
    assert not live

@pytest.mark.asyncio
async def test_atomic_stage_budget_preserves_tail_allowance(tmp_path):
    value=input9(max_calls=12,max_tokens=100000);repo,row=admitted(tmp_path,value);repo.claim_generation(row.generation_id)
    store=PlanningStore(repo.db_path,row.generation_id,row.input_hash,value.report_budget)
    async def reserve(_):
        try:await asyncio.to_thread(store.reserve,'extraction',10,10,2);return True
        except ReportPlanningError:return False
    result=await asyncio.gather(*(reserve(i) for i in range(20)))
    assert sum(result)==2 and store.usage()['calls']==2
    store.reserve('chapter',10,10)

@pytest.mark.asyncio
async def test_full_review_problem_cannot_publish_if_repair_still_fails(tmp_path):
    class BadCoherence(TimedModel):
        async def chat_completion(self,system,prompt,**kwargs):
            payload=json.loads(prompt)
            if payload.get('operation')=='coherence_review':
                chapter=payload['sections'][0]
                return {'content':json.dumps({'issues':[{'section_id':chapter['section_id'],'paragraph_index':0,
                    'quote':chapter['paragraphs'][0][:12],'reason':'概述存在未解决的跨章矛盾'}]},ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    value=input9();repo,row=admitted(tmp_path,value)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),BadCoherence())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='failed' and done.report_id is None
    assert '跨章' in done.error_message

@pytest.mark.asyncio
async def test_closure_body_hash_is_enforced_on_read(tmp_path):
    report,_,_=await execute(tmp_path,input9(),TimedModel())
    raw=report.model_dump(mode='json');raw['organization']['validation']['closure_body_sha256']='0'*64
    with pytest.raises(ValueError,match='最终主体'):GenerationReportManifest.model_validate(raw)

@pytest.mark.asyncio
async def test_multiple_reports_share_four_request_slots(tmp_path):
    class Shared(TimedModel):
        running=0;maximum=0
        async def chat_completion(self,*args,**kwargs):
            Shared.running+=1;Shared.maximum=max(Shared.maximum,Shared.running)
            try:return await super().chat_completion(*args,**kwargs)
            finally:Shared.running-=1
    roots=[tmp_path/'a',tmp_path/'b']
    for root in roots:root.mkdir()
    await asyncio.gather(*(execute(root,input9(),Shared(.03)) for root in roots))
    assert Shared.maximum==4 and Shared.running==0

@pytest.mark.asyncio
async def test_closing_may_reference_other_validated_body_findings(tmp_path):
    class OptionalFinding(TimedModel):
        async def chat_completion(self,system,prompt,**kwargs):
            payload=json.loads(prompt)
            response=await super().chat_completion(system,prompt,**kwargs)
            if payload.get('completed_body'):
                extra=next((c for c in payload['claims'] if c['claim_id'] not in payload.get('required_claim_ids',[])),None)
                if extra:
                    raw=json.loads(response['content'])
                    raw['paragraphs'].append({'text':'主体还记载了以下待核对观察：'+extra['statement']+'该观察不能单独证明行为目的。',
                        'claim_ids':[extra['claim_id']],'citation_ids':list(dict.fromkeys(r['citation_id'] for r in extra['references']))})
                    response['content']=json.dumps(raw,ensure_ascii=False)
            return response
    report,_,_=await execute(tmp_path,input9(),OptionalFinding())
    body={fid for c in report.organization.plan.chapters if c.role not in ('scope','conclusion') for fid in c.finding_ids}
    for chapter in report.organization.plan.chapters:
        if chapter.role not in ('scope','conclusion'):continue
        used={fid for p in report.organization.paragraphs if p.section_id==chapter.section_id for fid in p.finding_ids}
        assert set(chapter.required_finding_ids)<used<=body

@pytest.mark.asyncio
async def test_editorial_advice_is_recorded_without_becoming_a_fact_conflict(tmp_path):
    class Advice(TimedModel):
        async def chat_completion(self,system,prompt,**kwargs):
            value=json.loads(prompt)
            if value.get('operation')=='coherence_review':
                assert all('references' in finding for finding in value['findings'])
                chapter=value['sections'][0]
                return {'content':json.dumps({'issues':[{'kind':'repetition','section_id':chapter['section_id'],
                    'paragraph_index':0,'quote':chapter['paragraphs'][0][:12],'reason':'可压缩部分摘要复述'}]},ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    report,_,_=await execute(tmp_path,input9(),Advice())
    assert report.organization.validation['coherence_status']=='auxiliary_checks_passed'
    assert report.organization.validation['coherence_advisories']

@pytest.mark.asyncio
async def test_invalid_review_item_does_not_erase_valid_blocking_issue(tmp_path):
    class Mixed(TimedModel):
        async def chat_completion(self,system,prompt,**kwargs):
            value=json.loads(prompt)
            if value.get('operation')=='coherence_review':
                chapter=value['sections'][0]
                return {'content':json.dumps({'issues':[{'kind':'contradiction','section_id':chapter['section_id'],
                    'paragraph_index':0,'quote':chapter['paragraphs'][0][:12],'reason':'明确冲突尚未解决'},
                    {'section_id':'foreign','paragraph_index':999,'quote':'不存在的正文片段','reason':'无效意见'}]},ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    value=input9();repo,row=admitted(tmp_path,value)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),Mixed())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='failed' and done.report_id is None

@pytest.mark.asyncio
async def test_whole_repair_then_chapter_repair_use_distinct_immutable_keys(tmp_path):
    class NestedRepair(TimedModel):
        whole_calls=0;second_repair=False
        async def chat_completion(self,system,prompt,**kwargs):
            payload=json.loads(prompt)
            if payload.get('operation')=='coherence_review':
                self.whole_calls+=1
                if self.whole_calls==1:
                    chapter=payload['sections'][1]
                    self.target=chapter['section_id']
                    issues=[{'kind':'contradiction','section_id':self.target,'paragraph_index':0,'quote':chapter['paragraphs'][0][:12],'reason':'合成的跨章问题需修复'}]
                else:issues=[]
                return {'content':json.dumps({'issues':issues},ensure_ascii=False),'model':'test-model'}
            if payload.get('operation')=='semantic_review' and self.whole_calls==1 and payload['section_id']==self.target and not self.second_repair:
                self.second_repair=True
                return {'content':json.dumps({'issues':[{'paragraph_index':0,'quote':payload['paragraphs'][0][:12],'reason':'合成的逐章问题仍需修复'}]},ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    model=NestedRepair();report,repo,row=await execute(tmp_path,input9(),model)
    assert model.second_repair and report.organization.validation['coherence_status']=='auxiliary_checks_passed'
    with sqlite3.connect(repo.db_path) as db:
        keys={r[0] for r in db.execute("SELECT artifact_key FROM report_planning_artifacts WHERE generation_id=? AND stage='chapter_validated'",(row.generation_id,))}
    assert model.target+'-coherence-rewrite' in keys
    assert model.target+'-coherence-review-rewrite' in keys
