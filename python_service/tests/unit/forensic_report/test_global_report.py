import asyncio,hashlib,json,sqlite3
from pathlib import Path
import pytest
from httpserver.services.forensic_report.models import (ReportGenerationEnvelopeV8,EnvelopeEvidenceItemV3,
    EnvelopeSnapshotV3,NeutralMaterial,material_scope_hash,StructuredReportSection,GenerationReportManifest,parse_generation_envelope)
from httpserver.services.investigation.models import FileSnapshotPayload
from httpserver.services.forensic_report.global_report_models import ReportBudget,FindingSuggestion,SourceQuote,PlannedChapter
from httpserver.services.forensic_report.global_report_store import PlanningStore,ReportPlanningError
from httpserver.services.forensic_report.global_report import generate_global_report,representative_findings
from httpserver.services.forensic_report.global_report_validation import validate_finding,validate_body,validate_chapter,section_adapter,validate_published
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.investigation.acquisition import canonical_json

def envelope(count=4,**overrides):
    items=[];materials=[]
    for index in range(count):
        key=f'file:/测试材料/记录{index}.txt';text=f'原始记录包含账号甲的配置项目，来源编号{index}。该记录属于采集材料，需要结合其他来源判断活动。'
        h=hashlib.sha256(text.encode()).hexdigest()
        items.append(EnvelopeEvidenceItemV3(evidence_key=key,report_status='main',snapshot=EnvelopeSnapshotV3(task_id='task',evidence_key=key,evidence_type='file',captured_at=1,payload=FileSnapshotPayload(normalized_path=f'/测试材料/记录{index}.txt'))))
        materials.append(NeutralMaterial(material_id=f'm{index:04}',evidence_key=key,kind='text',text=text,source_sha256=h,content_sha256=h,original_characters=len(text),status='ready'))
    items=tuple(sorted(items,key=lambda i:i.evidence_key));materials=tuple(sorted(materials,key=lambda m:m.evidence_key))
    return ReportGenerationEnvelopeV8(task_id='task',prompt_version='final-report:evidence-only:v3',analysis_mode='evidence_only',case_description='',
        main_evidence=items,allowed_report_evidence_ids=tuple(i.evidence_key for i in items),neutral_materials=materials,evidence_scope_hash=material_scope_hash(materials),
        report_budget=ReportBudget(**{'context_limit':65536,'body_target_chars':8000,'max_calls':512,**overrides}))

def admitted(tmp_path,value):
    repo=ReportRepository(tmp_path/'reports.db');raw=canonical_json(value)
    row=repo.create_generation_input('task',requested_by='test',input_schema_version=value.schema_version,prompt_version=value.prompt_version,
        input_envelope_json=raw,input_hash=hashlib.sha256(raw.encode()).hexdigest())
    return repo,row

class Model:
    def __init__(self,oversize=False):self.calls=[];self.oversize=oversize
    async def chat_completion(self,system,prompt,**kwargs):
        value=json.loads(prompt);self.calls.append((value,kwargs))
        if value.get('operation')=='semantic_review':result={'issues':[]}
        elif 'windows' in value:
            result={'findings':[{'statement':f"材料记载了账号甲的配置，{row['name']}的实际使用仍需核实。",'kind':'observation','topic':('activity','identity','connections')[int(row['material_id'][1:])%3],
                'entities':['账号甲'],'action':'配置记录','time_text':'','time_basis':'unknown',
                'supporting_refs':[{'material_id':row['material_id'],'quote':row['text'].split('。')[0]+'。','character_start':row['window_start']}],
                'counter_refs':[],'limitations':['配置存在不能证明实际执行'],'alternatives':[],'priority_hint':'P2','case_context_quote':''} for row in value['windows']]}
        else:
            claims=value['claims'];ids=[c['claim_id'] for c in claims];cids=list(dict.fromkeys(r['citation_id'] for c in claims for r in c['references']))
            body=(f"{value['heading']}围绕已有记录展开。"+'；'.join(c['statement'] for c in claims)+'这些观察提供了核查配置与使用关系的起点，但不能自动推断执行主体或实际操作。需要结合来源形成过程解释记录含义，避免将配置存在替代行为判断。')
            if self.oversize:body+='超长内容'*2000
            result={'section_id':value['section_id'],'used_claim_ids':ids,'paragraphs':[{'text':body,'claim_ids':ids,'citation_ids':cids}]}
        return {'content':json.dumps(result,ensure_ascii=False),'model':'test-model','finish_reason':'stop'}

@pytest.mark.asyncio
async def test_original_executor_publishes_global_body_and_separate_appendix(tmp_path):
    value=envelope();repo,row=admitted(tmp_path,value);model=Model();writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,model)._execute(row.generation_id)
    completed=repo.get_generation_input(row.generation_id)
    assert completed.status=='completed',completed.error_message
    manifest=GenerationReportManifest.model_validate(writer.read_manifest('task',completed.report_id))
    assert manifest.schema_version=='1.3' and 4<=len(manifest.sections)<=6
    assert manifest.appendices and manifest.organization.body_chars<=20000
    assert manifest.organization.validation['max_section_share']<=0.35
    assert len(manifest.organization.paragraphs)>0
    with sqlite3.connect(repo.db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM report_planning_artifacts').fetchone()[0]>=8
    assert parse_generation_envelope(canonical_json(value))==value

@pytest.mark.asyncio
async def test_oversize_retries_never_publish_partial_or_list_fallback(tmp_path):
    value=envelope();repo,row=admitted(tmp_path,value)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),Model(oversize=True))._execute(row.generation_id)
    result=repo.get_generation_input(row.generation_id)
    assert result.status=='failed' and result.report_id is None
    assert not list((tmp_path/'snapshots').glob('**/manifest.json'))

def test_exact_source_span_hash_and_ambiguous_quote_are_enforced():
    value=envelope(1);source=value.neutral_materials[0];full={source.material_id:source};window={'material_id':source.material_id,'window_start':0,'text':source.text}
    suggestion=FindingSuggestion(statement='材料包含账号甲的配置记录',kind='observation',topic='identity',entities=('账号甲',),supporting_refs=(SourceQuote(material_id=source.material_id,quote='账号甲'),))
    finding,refs=validate_finding(suggestion,[window],full,value)
    assert refs[0].content_sha256==source.content_sha256 and source.text[refs[0].character_start:refs[0].character_end]=='账号甲'
    corrected=suggestion.model_copy(update={'supporting_refs':(SourceQuote(material_id=source.material_id,quote='账号甲',character_start=999),)})
    _,corrected_refs=validate_finding(corrected,[window],full,value)
    assert corrected_refs[0].character_start==source.text.index('账号甲') and corrected_refs[0].position_resolution=='unique_quote_corrected'
    with pytest.raises(ReportPlanningError):validate_finding(suggestion.model_copy(update={'time_text':'2028-01-01'}),[window],full,value)
    with pytest.raises(ReportPlanningError):validate_finding(suggestion.model_copy(update={'supporting_refs':(SourceQuote(material_id='m9999',quote='账号甲'),)}),[window],full,value)
    repeated='😀账号甲，账号甲'
    source=source.model_copy(update={'text':repeated,'content_sha256':hashlib.sha256(repeated.encode()).hexdigest()})
    window={**window,'text':repeated}
    with pytest.raises(ReportPlanningError,match='多处'):validate_finding(suggestion,[window],{source.material_id:source},value)
    explicit=suggestion.model_copy(update={'supporting_refs':(SourceQuote(material_id=source.material_id,quote='账号甲',character_start=1),)})
    _,refs=validate_finding(explicit,[window],{source.material_id:source},value)
    assert refs[0].character_start==1 and refs[0].character_end==4

@pytest.mark.asyncio
async def test_320_findings_remain_globally_bounded_with_explicit_coverage(tmp_path):
    value=envelope(320);repo,row=admitted(tmp_path,value);writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,Model())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='completed',done.error_message
    result=GenerationReportManifest.model_validate(writer.read_manifest('task',done.report_id))
    assert len(result.organization.findings)==320 and 4<=len(result.sections)<=6
    assert result.organization.body_chars<=20000
    assert result.organization.validation['max_section_share']<=0.35
    assert len(result.organization.coverage)==320
    assert all(row.get('body_status')=='main' or row.get('exclusion_reason') for row in result.organization.coverage)

@pytest.mark.asyncio
async def test_54_paragraph_response_is_rejected_without_appending(tmp_path):
    class TooMany(Model):
        async def chat_completion(self,system,prompt,**kwargs):
            response=await super().chat_completion(system,prompt,**kwargs)
            value=json.loads(prompt)
            if 'section_id' in value and value.get('operation')!='semantic_review':
                raw=json.loads(response['content']);raw['paragraphs']*=54;response['content']=json.dumps(raw,ensure_ascii=False)
            return response
    value=envelope();repo,row=admitted(tmp_path,value)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),TooMany())._execute(row.generation_id)
    assert repo.get_generation_input(row.generation_id).status=='failed'
    assert not list((tmp_path/'snapshots').glob('**/manifest.json'))

def test_whole_body_limits_cover_overview_and_conclusion():
    budget=ReportBudget()
    with pytest.raises(ReportPlanningError,match='4至6'):validate_body([StructuredReportSection(heading='章节',content='正文')]*54,budget)
    sections=[StructuredReportSection(heading=str(i),content=str(i)*100) for i in range(4)]
    sections[-1]=StructuredReportSection(heading='结论',content='结论内容'*3000)
    with pytest.raises(ReportPlanningError,match='35%'):validate_body(sections,budget)

def test_budget_retry_reservations_do_not_reset_and_checkpoints_are_immutable(tmp_path):
    value=envelope(max_calls=12,max_tokens=4096);repo,row=admitted(tmp_path,value);repo.claim_generation(row.generation_id)
    store=PlanningStore(repo.db_path,row.generation_id,row.input_hash,value.report_budget)
    store.save('facts','one',{'value':1})
    with pytest.raises(ReportPlanningError):store.save('facts','one',{'value':2})
    for i in range(4):store.reserve('test',512,512)
    same=PlanningStore(repo.db_path,row.generation_id,row.input_hash,value.report_budget)
    with pytest.raises(ReportPlanningError):same.reserve('test',1,1)

def test_entity_elsewhere_is_anchored_as_presence_not_confirmed_relationship():
    value=envelope(1);source=value.neutral_materials[0]
    text='动作记录已经保存。其他字段记载账号甲，不能仅据共同出现确认关联。'
    source=source.model_copy(update={'text':text,'content_sha256':hashlib.sha256(text.encode()).hexdigest()})
    candidate=FindingSuggestion(statement='记录涉及账号甲，需要进一步核对关系。',kind='observation',topic='identity',entities=('账号甲',),
        supporting_refs=(SourceQuote(material_id=source.material_id,quote='动作记录已经保存。'),))
    finding,spans=validate_finding(candidate,[{'material_id':source.material_id,'window_start':0,'text':text}],{source.material_id:source},value)
    assert finding.kind=='inference' and finding.entity_spans['账号甲']
    assert len(finding.supporting_spans)==1 and any(s.position_resolution=='entity_presence_only' for s in spans)
    assert '尚不能' in finding.limitations[0]

@pytest.mark.asyncio
async def test_invalid_candidate_does_not_erase_other_valid_findings(tmp_path):
    class Mixed(Model):
        async def chat_completion(self,system,prompt,**kwargs):
            result=await super().chat_completion(system,prompt,**kwargs)
            if 'windows' in json.loads(prompt):
                value=json.loads(result['content']);bad=dict(value['findings'][0]);bad['supporting_refs']=[{'material_id':'foreign','quote':'伪造'}]
                value['findings'].append(bad);result['content']=json.dumps(value,ensure_ascii=False)
            return result
    value=envelope();repo,row=admitted(tmp_path,value);writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,Mixed())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id);assert done.status=='completed',done.error_message
    report=GenerationReportManifest.model_validate(writer.read_manifest('task',done.report_id))
    assert len(report.organization.findings)==4 and report.organization.quality=='preliminary'
    assert all(s.material_id!='foreign' for s in report.organization.spans)

@pytest.mark.asyncio
async def test_v7_frozen_input_executes_its_recorded_legacy_contract(tmp_path):
    from httpserver.services.forensic_report.models import ReportGenerationEnvelopeV7
    data=envelope(1).model_dump(mode='json');data.pop('report_budget');data.pop('derivation_versions')
    data.update(schema_version=7,prompt_version='final-report:evidence-only:v2')
    value=ReportGenerationEnvelopeV7.model_validate(data)
    class Legacy:
        async def chat_completion(self,system,prompt,**kwargs):
            body=json.loads(prompt)
            if 'questions' in body:
                result={'classifications':[{'evidence_key':m['evidence_key'],'material_type':'document','topics':[],
                    'relations':[],'key_issue':False,'reason':'核对原始记载','basis_quote':m['basis_text'][:8]} for m in body['materials']]}
            elif 'validated_directions' in body:
                result={'sections':[{'heading':heading,'content':(heading+'仅依据既有冻结材料解释可见记录，当前范围不等于全盘覆盖，具体主体和行为仍需人工核对。')*3} for heading in ('来源观察','解释边界')]}
            else:
                m=body['materials'][0]
                result={'directions':[{'title':'材料记载','description':'原始记录中的配置仍需结合上下文核对。','finding_kind':'observation',
                    'supporting_refs':[{'material_id':m['material_id'],'quote':m['text'][:8]}]}]}
            return {'content':json.dumps(result,ensure_ascii=False),'model':'legacy-test'}
    repo,row=admitted(tmp_path,value);writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,Legacy())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id);assert done.status=='completed',done.error_message
    raw=writer.read_manifest('task',done.report_id)
    assert raw['schema_version']=='1.2' and 'organization' not in raw and 'appendices' not in raw


@pytest.mark.parametrize('qualification', ['仍需结合其他来源判断', '有待核实', '尚待进一步确认', '尚未证实', '未证明其实际执行', '不证明实际执行', '不等于任务实际执行', '以原始字段为限'])
def test_chinese_qualifications_do_not_turn_inference_into_false_positive(qualification):
    value=envelope(1);source=value.neutral_materials[0]
    candidate=FindingSuggestion(statement='配置记载与实际使用关系需要核对',kind='inference',topic='connections',
        limitations=('配置不证明实际运行',),supporting_refs=(SourceQuote(material_id=source.material_id,quote=source.text),))
    finding,refs=validate_finding(candidate,[{'material_id':source.material_id,'window_start':0,'text':source.text}],{source.material_id:source},value)
    findings={finding.finding_id:finding};spans={r.span_id:r for r in refs};materials={source.material_id:source};cids={source.material_id:'c0001'}
    chapter=PlannedChapter(section_id='s1',role='connections',heading='关联解释',brief='核对配置和运行的关系',finding_ids=(finding.finding_id,),target_chars=800,max_chars=1200)
    adapter=section_adapter(chapter,findings,spans,materials,cids,'scope','plan')
    raw={'section_id':'s1','used_claim_ids':[], 'paragraphs':[{'text':'材料记录账号甲的配置项目，配置记录与实际使用之间的关系'+qualification+'。','claim_ids':[finding.finding_id],'citation_ids':['c0001']}]}
    output,_=validate_chapter(raw,chapter,adapter,findings,spans,materials,cids)
    assert output.used_claim_ids==[finding.finding_id]
    raw['paragraphs'][0]['text']='配置记录证明账号甲使用了这台设备，并且执行了其中的程序。'
    with pytest.raises(ReportPlanningError,match='确定事实'):
        validate_chapter(raw,chapter,adapter,findings,spans,materials,cids)


@pytest.mark.asyncio
async def test_unresolved_semantic_issue_cannot_pass_when_repeat_review_is_unavailable(tmp_path):
    class ReviewFails(Model):
        reviews=0
        async def chat_completion(self,system,prompt,**kwargs):
            payload=json.loads(prompt)
            if payload.get('operation')=='semantic_review':
                self.reviews+=1
                result={'issues':[{'paragraph_index':0,'quote':payload['paragraphs'][0][:12],'reason':'段落关系解释仍不充分'}]} if self.reviews==1 else {'issues':'无效复核响应'}
                return {'content':json.dumps(result,ensure_ascii=False),'model':'test-model'}
            return await super().chat_completion(system,prompt,**kwargs)
    value=envelope();repo,row=admitted(tmp_path,value);writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,ReviewFails())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='failed' and '未完成复核' in done.error_message
    assert done.report_id is None and not list((tmp_path/'snapshots').glob('**/manifest.json'))


@pytest.mark.asyncio
async def test_published_manifest_cannot_omit_claims_or_support_mappings(tmp_path):
    value=envelope();repo,row=admitted(tmp_path,value);writer=GenerationReportWriter(tmp_path)
    await ReportGenerationExecutor(repo,writer,Model())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    report=GenerationReportManifest.model_validate(writer.read_manifest('task',done.report_id))
    organization=report.organization;binding=organization.paragraphs[0]
    for update in ({'finding_ids':()}, {'span_ids':()}):
        forged=organization.model_copy(update={'paragraphs':(binding.model_copy(update=update),*organization.paragraphs[1:])})
        with pytest.raises(ValueError,match='映射遗漏'):
            validate_published(forged,report.sections,report.appendices,report.stage_analysis.materials,report.citations)


def test_repetitive_source_family_does_not_monopolize_overview():
    value=envelope(24);findings=[];spans={};materials={}
    for index,source in enumerate(value.neutral_materials):
        table='prefetch_files' if index<20 else ('browser_history','scheduled_tasks','windows_services','usb_devices')[index-20]
        source=source.model_copy(update={'source_provenance':{'source_table':table}});materials[source.material_id]=source
        candidate=FindingSuggestion(statement='来源记录需要结合设备上下文解释',kind='observation',topic='activity',priority_hint='P2',
            supporting_refs=(SourceQuote(material_id=source.material_id,quote=source.text),))
        finding,refs=validate_finding(candidate,[{'material_id':source.material_id,'window_start':0,'text':source.text}],materials,value)
        # Force a stable order that would otherwise pick only Prefetch records.
        finding=finding.model_copy(update={'finding_id':f'f_{index:04}'})
        findings.append(finding);spans.update((r.span_id,r) for r in refs)
    chosen=representative_findings(findings,5,spans,materials)
    families={materials[spans[f.supporting_spans[0]].material_id].source_provenance['source_table'] for f in chosen}
    assert len(families)==5
    assert [f.finding_id for f in chosen]==[f.finding_id for f in representative_findings(list(reversed(findings)),5,spans,materials)]


def test_exported_evidence_cannot_define_html_or_markdown_images():
    from httpserver.services.forensic_report.global_report_presentation import markdown_literal
    value=markdown_literal('<img src="https://example.invalid/pixel"> ![截图](https://example.invalid/image) `代码`')
    assert '<img' not in value and '![截图](' not in value
    assert '&lt;img' in value and r'\!\[截图\]' in value and r'\`代码\`' in value
