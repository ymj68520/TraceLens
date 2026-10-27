import json
from types import SimpleNamespace
import pytest
from httpserver.services.forensic_report.grounded_review import verified_prefetch_statement,resolve_issues
from httpserver.services.forensic_report.generation_sources import material
from httpserver.services.forensic_report.global_report import representative_findings
from test_report_concurrency import input9,execute,TimedModel
from httpserver.services.forensic_report.models import ReportGenerationEnvelopeV9


def source(cid='c1',count=5,time='2025-05-20T09:59:51.387547Z',program='SAMPLE.EXE'):
    return {'citation_id':cid,'material_id':'m1','kind':'parsed_text',
        'text':f'# Prefetch 执行记录\n可执行文件名：{program}\n执行次数：{count}\n- 槽位 0：{time}；原始 FILETIME：133922087913875476'}


def test_original_execution_fields_override_omission_in_summary():
    records=[source()]
    assert verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 5',records)
    assert verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 5，最近一次为 2025-05-20T09:59:51Z',records)
    assert not verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 6',records)
    assert not verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 5，最近一次为 2025-05-20T09:59:52Z',records)
    assert not verified_prefetch_statement('OTHER.EXE 预取记录显示执行次数为 5',records)
    assert not verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 5，并实施了攻击',records)
    assert not verified_prefetch_statement('SAMPLE.EXE 预取记录显示执行次数为 5',[{**records[0],'kind':'machine_visual'}])


def test_two_records_keep_distinct_times():
    records=[source('c1',9,'2025-05-20T09:59:53.079780Z'),source('c2',9,'2025-05-20T09:59:53.758356Z')]
    quote='SAMPLE.EXE 的两份预取记录均显示执行次数为 9，最近一次分别为 2025-05-20T09:59:53.079780Z 与 2025-05-20T09:59:53.758356Z'
    assert verified_prefetch_statement(quote,records)
    assert not verified_prefetch_statement(quote,[records[0]])


class Provider:
    output_limit=4096
    def __init__(self,decision):
        self.calls=[];self.saved=[];self.decision=decision
        self.store=SimpleNamespace(save=lambda *args:self.saved.append(args))
    def fits(self,*args,**kwargs):return True
    async def call(self,*args,**kwargs):
        self.calls.append(args)
        return {'decisions':[self.decision]}


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict,quote,blocked',[('supported','服务只绑定内网地址',False),('supported','来源中不存在的内容',True),('unsupported','服务只绑定内网地址',True),('uncertain','服务只绑定内网地址',True)])
async def test_disputed_claim_needs_valid_cited_support(verdict,quote,blocked):
    records=[{'citation_id':'c1','kind':'text','text':'配置说明：服务只绑定内网地址，尚未核对实际监听状态。'}]
    issue={'paragraph_index':0,'quote':'材料显示服务绑定内网地址','reason':'审校认为缺少该字段'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    model=Provider({'issue_index':0,'verdict':verdict,'source_quotes':[{'citation_id':'c1','quote':quote}],'reason':'依据冻结记录核对该表述'})
    result,_=await resolve_issues([issue],paragraphs,records,model,'first')
    assert bool(result)==blocked
    await resolve_issues([issue],paragraphs,records,model,'again')
    assert len(model.calls)==1


@pytest.mark.asyncio
async def test_uncited_record_cannot_clear_an_objection():
    model=Provider({'issue_index':0,'verdict':'supported','source_quotes':[{'citation_id':'foreign','quote':'记录中的执行次数是五次'}],'reason':'来源支持'})
    issue={'paragraph_index':0,'quote':'报告中的执行次数是五次','reason':'需核对原记录'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    records=[{'citation_id':'c1','kind':'text','text':'没有执行次数'}, {'citation_id':'foreign','kind':'text','text':'记录中的执行次数是五次'}]
    remaining,note=await resolve_issues([issue],paragraphs,records,model,'check')
    assert remaining and note
    assert all(r['citation_id']=='c1' for r in model.calls[0][3]['source_records'])


def test_server_sources_take_precedence_over_language_resources():
    values=[];spans={};materials={}
    for i,path in enumerate(['/app/_locales/fr/messages.json','/app/_locales/en/messages.json','/www/wwwroot/site/application/database.php','/var/log/secure']):
        mid=f'm{i:04}';sid=f's{i}';materials[mid]=material(mid,'file:'+path,text='有来源的观察',kind='text',status='ready')
        spans[sid]=SimpleNamespace(material_id=mid)
        values.append(SimpleNamespace(finding_id=f'f{i}',supporting_spans=(sid,),counter_spans=(),priority_hint='P2',kind='observation',time_sort_key=None,topic='environment'))
    selected=representative_findings(values,2,spans,materials,focus=True)
    assert {f.finding_id for f in selected}=={'f2','f3'}


@pytest.mark.parametrize('path', [
    '/www/wwwroot/site/public/static/plugs/ckeditor/lang/en.js',
    '/www/wwwroot/site/public/static/plugins/editor/config.js',
    '/usr/src/kernels/1/drivers/net/Kconfig',
    '/usr/local/curl/share/man/man3/example.3',
    '/var/log/anaconda/package.hdr',
])
def test_server_resource_paths_do_not_drive_the_report_main_thread(path):
    from httpserver.services.forensic_report.report_focus import role
    assert role(material('m0001', 'file:'+path))[1] == 'software_resource'
    assert role(material('m0002', 'file:/www/wwwroot/site/public/js/checkout.js'))[1] == 'application_logic'
    assert role(material('m0003', 'file:/var/log/anaconda/anaconda.log'))[1] == 'activity'


@pytest.mark.asyncio
async def test_v5_runs_the_existing_executor_and_keeps_closure(tmp_path):
    raw=input9(count=12).model_dump(mode='json');raw['prompt_version']='final-report:evidence-only:v5'
    report,_,_=await execute(tmp_path,ReportGenerationEnvelopeV9.model_validate(raw),TimedModel(delay=0))
    assert report.schema_version=='1.4'
    assert report.prompt_version.endswith(':v5')
    assert report.organization.validation['coherence_status']=='auxiliary_checks_passed'


@pytest.mark.asyncio
@pytest.mark.parametrize('decision,blocked', [('clear_objection',False),('keep_objection',True),('needs_review',True)])
async def test_v6_actions_have_explicit_meaning(decision, blocked):
    records=[{'citation_id':'c1','kind':'text','text':'会话记录：同一地址两次成功认证。'}]
    issue={'paragraph_index':0,'quote':'同一地址两次成功认证','reason':'需核对实际记录'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    model=Provider({'issue_index':0,'decision':decision,'source_quotes':[{'citation_id':'c1','quote':'同一地址两次成功认证'}],'reason':'已检查所引原记录'})
    kept,note=await resolve_issues([issue],paragraphs,records,model,'v6',protocol=2)
    assert bool(kept)==blocked and note is None
    assert len(model.calls)==1


@pytest.mark.asyncio
async def test_v6_ambiguous_old_verdict_requires_an_explicit_correction():
    records=[{'citation_id':'c1','kind':'text','text':'配置说明：服务只绑定内网地址。'}]
    issue={'paragraph_index':0,'quote':'材料显示服务只绑定内网地址','reason':'需核对来源'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    class Correction(Provider):
        async def call(self,*args,**kwargs):
            self.calls.append(args)
            common={'issue_index':0,'source_quotes':[{'citation_id':'c1','quote':'服务只绑定内网地址'}],'reason':'原记录支持该段落，异议不成立'}
            return {'decisions':[{**common,**({'verdict':'unsupported'} if len(self.calls)==1 else {'decision':'clear_objection'})}]}
    model=Correction(None)
    kept,note=await resolve_issues([issue],paragraphs,records,model,'v6',protocol=2)
    assert not kept and note is None and len(model.calls)==2
    assert 'correction' in model.calls[1][3]
    assert model.calls[0][1]!=model.calls[1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,blocked', [(None,True),(-1,True),(1,True),(0,False),(5,False)])
async def test_v6_repeated_quotes_need_a_verified_character_position(offset,blocked):
    records=[{'citation_id':'c1','kind':'text','text':'会话结束\n会话结束'}]
    issue={'paragraph_index':0,'quote':'本记录包含会话结束条目','reason':'需核对来源'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    ref={'citation_id':'c1','quote':'会话结束'}
    if offset is not None:ref['character_start']=offset
    model=Provider({'issue_index':0,'decision':'clear_objection','source_quotes':[ref],'reason':'核对冻结原文中的具体位置'})
    kept,note=await resolve_issues([issue],paragraphs,records,model,'v6',protocol=2)
    assert bool(kept)==blocked and bool(note)==blocked
    assert len(model.calls)==(2 if blocked else 1)


@pytest.mark.asyncio
async def test_unique_verbatim_quote_repairs_a_bad_model_offset_with_an_audit():
    records=[{'citation_id':'c1','kind':'text','text':'来源记录：会话在此刻结束。'}]
    issue={'paragraph_index':0,'quote':'日志显示该会话在此刻结束','reason':'需要核对原文'}
    paragraphs={('',0):{'text':issue['quote'],'citation_ids':['c1']}}
    model=Provider({'issue_index':0,'decision':'clear_objection','reason':'所引原记录包含这项事实',
        'source_quotes':[{'citation_id':'c1','quote':'会话在此刻结束','character_start':0}]})
    kept,note=await resolve_issues([issue],paragraphs,records,model,'unique',protocol=2)
    assert not kept and note is None
    outcome=model.saved[-1][2]['outcome']['decisions'][0]['source_quotes'][0]
    assert outcome['character_start']==5 and outcome['original_character_start']==0
    assert outcome['position_resolution']=='unique_quote_corrected'


@pytest.mark.asyncio
async def test_v6_runs_the_existing_executor_and_keeps_closure(tmp_path):
    raw=input9(count=12).model_dump(mode='json');raw['prompt_version']='final-report:evidence-only:v6'
    report,_,_=await execute(tmp_path,ReportGenerationEnvelopeV9.model_validate(raw),TimedModel(delay=0))
    assert report.schema_version=='1.4' and report.prompt_version.endswith(':v6')
    assert report.organization.validation['coherence_status']=='auxiliary_checks_passed'


@pytest.mark.asyncio
async def test_v6_persistent_objection_still_blocks_after_bounded_repairs(tmp_path):
    from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
    from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
    from test_report_concurrency import admitted
    class Persistent(TimedModel):
        whole_calls=0
        async def chat_completion(self,system,prompt,**kwargs):
            payload=json.loads(prompt)
            if payload.get('operation')=='grounded_review_resolution':
                assert payload['review_protocol']=='explicit-decision:v2'
                return {'content':json.dumps({'decisions':[{'issue_index':i,'decision':'keep_objection','source_quotes':[],
                    'reason':'合成测试：已知来源问题仍未解决'} for i in range(len(payload['issues']))]},ensure_ascii=False),'model':'test-model'}
            if payload.get('operation')=='coherence_review':
                self.whole_calls+=1;chapter=payload['sections'][0]
                return {'content':json.dumps({'issues':[{'kind':'unsupported_claim','section_id':chapter['section_id'],
                    'paragraph_index':0,'quote':chapter['paragraphs'][0][:12],'reason':'合成测试：来源仍不足'}]},ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    raw=input9(count=12).model_dump(mode='json');raw['prompt_version']='final-report:evidence-only:v6'
    value=ReportGenerationEnvelopeV9.model_validate(raw);repo,row=admitted(tmp_path,value);model=Persistent(delay=0)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),model)._execute(row.generation_id)
    result=repo.get_generation_input(row.generation_id)
    assert model.whole_calls==3
    assert result.status=='failed' and result.report_id is None
