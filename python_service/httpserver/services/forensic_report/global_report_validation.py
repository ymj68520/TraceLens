"""Source/paragraph/body checks independent of model generation and storage."""
from __future__ import annotations
import hashlib,re,json
from datetime import datetime
from .global_report_models import FrozenSpan,ReportFinding,digest,canonical,PLANNER_VERSION
from .global_report_store import ReportPlanningError
from ..report_rendering import (SectionRenderInput,SectionRenderClaim,SectionRenderClaimCitation,
    SectionRenderCitation,SectionRenderOutput,validate_section_render_output)

DATE=re.compile(r'(20\d{2}|19\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?')
PROCESS=re.compile(r'本批(?:次|材料)?|下一批|上一批|第\s*\d+\s*批|批次[一二三四五六七八九十\d]|分批生成|拼接章节|map.reduce',re.I)
INTERNAL=re.compile(r'(?<![A-Za-z0-9_])(?:m\d{3,}|f_[0-9a-f]{16,})(?![A-Za-z0-9_])')
# This is a phrasing guard, not proof that the paragraph is semantically sound.
# Keep ordinary Chinese qualifications used in real reports, including 仍需.
QUALIFIED=re.compile(r'可能|推断|假设|尚需|仍需|有待|尚待|待核|不能|未能|不足|无法|未证实|未证明|不证明|不等于|不代表|不构成|不意味着|以(?:原始|现有|当前|已知|冻结).{0,12}为限')
COUNTER_QUALIFIED=re.compile(r'但|然而|相反|差异|不一致|限制|尚需|仍需|有待|尚待|待核|未能|不能|未证实|未证明|不证明|不等于|不代表|不构成|不意味着')
def dates(text):return {f'{int(y):04}-{int(m):02}-{int(d):02}' for y,m,d in DATE.findall(text)}
def plain_body_chars(sections):return sum(len(s.heading)+len(s.content) for s in sections)

def terminology_errors(statement,sources):
    text='\n'.join(s.text for s in sources)
    errors=[]
    negated=bool(re.search(r'不能|不代表|不等于|不证明|不构成|不意味着|并非|无法证明|未能证明|未证实|尚不能|尚无法',statement))
    if 'known_hosts' in text and 'authorized_keys' not in text and re.search(r'免密(?:登录|授权)|登录授权|授权公钥',statement) and not negated:
        errors.append('known_hosts仅记录主机公钥信任，不能据此确认登录授权')
    tables={(s.source_provenance or {}).get('source_table') for s in sources}
    if tables and tables<={'windows_services','scheduled_tasks','amcache_entries'} and re.search(r'已经?执行|已经?运行|成功执行|实际执行|成功登录',statement) and not negated:
        errors.append('离线配置或缓存记录不能单独证明实际执行')
    if dates(statement)-dates(text):errors.append('正文出现来源没有支持的日期')
    return errors

def resolve_quote(ref,windows,materials):
    if ref.material_id not in materials:raise ReportPlanningError('引用了范围外材料')
    if not ref.quote.strip():raise ReportPlanningError('引文不能只有空白')
    source=materials[ref.material_id]
    positions=set()
    for window in windows:
        if window['material_id']!=ref.material_id:continue
        start=window['text'].find(ref.quote)
        while start>=0:
            positions.add(window['window_start']+start)
            start=window['text'].find(ref.quote,start+1)
    resolution=None
    if ref.character_start is not None and ref.character_start in positions:
        start=ref.character_start
    else:
        if len(positions)!=1:raise ReportPlanningError('引文缺失或存在多处匹配，必须明确位置')
        start=next(iter(positions))
        if ref.character_start is not None:resolution='unique_quote_corrected'
    end=start+len(ref.quote)
    if source.status=='unavailable' or source.text[start:end]!=ref.quote:raise ReportPlanningError('引文不匹配冻结来源')
    value={'material_id':ref.material_id,'evidence_key':source.evidence_key,'source_sha256':source.source_sha256,
           'content_sha256':source.content_sha256,'character_start':start,'character_end':end,'quote':ref.quote}
    return FrozenSpan(span_id='r_'+digest(value)[:24],position_resolution=resolution,**value)

def validate_finding(value,windows,materials,envelope):
    if not re.search(r'[\u3400-\u9fff]', value.statement):raise ReportPlanningError('发现说明必须使用中文，原始主体和引文保留原文')
    if any(text.strip() and not re.search(r'[\u3400-\u9fff]',text) for text in (*value.limitations,*value.alternatives)):
        raise ReportPlanningError('发现限制与其他解释必须使用中文，原始引文保留原文')
    supporting=tuple(resolve_quote(ref,windows,materials) for ref in value.supporting_refs)
    counter=tuple(resolve_quote(ref,windows,materials) for ref in value.counter_refs)
    context_only=not supporting and not counter
    if context_only and not (envelope.analysis_mode=='case_guided' and value.kind=='hypothesis' and value.case_context_quote):
        raise ReportPlanningError('观察或推断缺少材料来源')
    if value.kind in ('observation','inference') and not supporting:raise ReportPlanningError('观察或推断缺少支持片段')
    if value.kind!='observation' and not (value.limitations or value.alternatives):raise ReportPlanningError('推断和假设必须说明限制或其他解释')
    if value.case_context_quote and (envelope.analysis_mode!='case_guided' or value.case_context_quote not in envelope.case_description):
        raise ReportPlanningError('案情语境越界')
    raw='\n'.join(ref.quote for ref in (*supporting,*counter))
    entity_spans={};extra_refs=[];entities=[]
    cited={ref.material_id for ref in (*supporting,*counter)}
    for entity in value.entities:
        encoded=json.dumps(entity,ensure_ascii=False)[1:-1]
        if not entity.strip() or len(entity)>160:raise ReportPlanningError('主体名称为空或过长')
        if entity in raw or encoded in raw:entities.append(entity);continue
        # A document label identifies the source, not a person or actor.
        if any(w['material_id'] in cited and entity==w.get('name') for w in windows):continue
        anchors={}
        for window in windows:
            if window['material_id'] not in cited:continue
            source=materials[window['material_id']]
            for literal in dict.fromkeys((entity,encoded)):
                at=window['text'].find(literal)
                while at>=0 and len(anchors)<8:
                    left=max(0,at-40);right=min(len(window['text']),at+len(literal)+40)
                    text=window['text'][left:right]
                    if len(text)>300:break
                    start=window['window_start']+left
                    data={'material_id':source.material_id,'evidence_key':source.evidence_key,'source_sha256':source.source_sha256,
                          'content_sha256':source.content_sha256,'character_start':start,'character_end':start+len(text),'quote':text}
                    span=FrozenSpan(span_id='r_'+digest(data)[:24],position_resolution='entity_presence_only',**data)
                    anchors[span.span_id]=span
                    at=window['text'].find(literal,at+1)
        if not anchors:raise ReportPlanningError('主体名称在已发送的相关原文中不存在：'+entity)
        entities.append(entity);extra_refs.extend(anchors.values());entity_spans[entity]=tuple(sorted(anchors))
    if value.time_text and value.time_text not in raw:raise ReportPlanningError('时间表述不在引用片段中')
    if dates(value.statement)-dates(raw):raise ReportPlanningError('发现的日期没有来源支持')
    if PROCESS.search(value.statement) or INTERNAL.search(value.statement):raise ReportPlanningError('发现混入处理过程或内部标识')
    used=[materials[r.material_id] for r in supporting]
    issues=terminology_errors(value.statement,used)
    if issues:raise ReportPlanningError('；'.join(issues))
    time_key=None
    if value.time_basis=='record_time' and value.time_text:
        try:
            parsed=datetime.fromisoformat(value.time_text.replace('Z','+00:00'))
            if parsed.tzinfo is not None:
                from datetime import timezone
                time_key=parsed.astimezone(timezone.utc).isoformat()
        except ValueError:pass
    item=value.model_dump(mode='json');item.pop('supporting_refs');item.pop('counter_refs')
    item['entities']=tuple(entities)
    if entity_spans:
        item['entity_spans']=entity_spans
        if item['kind']=='observation':item['kind']='inference'
        item['limitations']=tuple(dict.fromkeys(('部分主体仅能在同材料其他位置确认出现，尚不能据此证明与该行为的关系',*item['limitations'])))
    item.update(time_sort_key=time_key,supporting_spans=tuple(r.span_id for r in supporting),counter_spans=tuple(r.span_id for r in counter))
    identity='f_'+digest(item)[:24]
    return ReportFinding(finding_id=identity,source_finding_ids=(identity,),**item),(*supporting,*counter,*extra_refs)

def section_adapter(chapter,findings,spans,materials,cids,scope_hash,plan_hash):
    claims=[];allowed=[]
    for key in chapter.finding_ids:
        finding=findings[key];edges=[]
        for relation,refs in (('supports',finding.supporting_spans),('contradicts',finding.counter_spans)):
            for ref in refs:
                cid=cids[spans[ref].material_id]
                if not any(edge.citation_id==cid and edge.relation==relation for edge in edges):edges.append(SectionRenderClaimCitation(citation_id=cid,relation=relation))
                if cid not in allowed:allowed.append(cid)
        claims.append(SectionRenderClaim(claim_id=key,claim_type=finding.kind,claim_text=finding.statement,citations=edges))
    by_cid={value:key for key,value in cids.items()}
    citations=[SectionRenderCitation(citation_id=cid,evidence_type=materials[by_cid[cid]].kind,
        snapshot={'material_id':by_cid[cid],'source_sha256':materials[by_cid[cid]].source_sha256}) for cid in allowed]
    return SectionRenderInput(dataset_hash=scope_hash,citation_graph_hash=digest([c.model_dump() for c in claims]),
        section_plan_hash=plan_hash,prompt_version='report-global-writing:v1',section_id=chapter.section_id,
        section_type=chapter.role,title=chapter.heading,claim_ids=list(chapter.finding_ids),allowed_citation_ids=allowed,claims=claims,citations=citations)

def validate_chapter(raw,chapter,adapter,findings,spans,materials,cids):
    output=SectionRenderOutput.model_validate(raw)
    # The paragraph mappings are authoritative. The model's redundant summary
    # array must not make a correctly grounded chapter fail solely by ordering.
    actual_used=list(dict.fromkeys(key for p in output.paragraphs for key in p.claim_ids))
    output=output.model_copy(update={'used_claim_ids':actual_used})
    issues=validate_section_render_output(adapter,output)
    if issues:raise ReportPlanningError('章节主张或引用越界：'+','.join(i.code for i in issues[:3]))
    if not output.paragraphs or len(output.paragraphs)>14:raise ReportPlanningError('章节段落数量不合规')
    for paragraph_index,paragraph in enumerate(output.paragraphs):
        if not re.search(r'[\u3400-\u9fff]', paragraph.text):raise ReportPlanningError('报告正文必须使用中文，原始引文保留原文')
        if not paragraph.claim_ids:raise ReportPlanningError(f'叙事段落必须绑定本轮发现：第{paragraph_index+1}段（{paragraph.text[:50]}）。请绑定支持该段的允许发现；无依据的衔接段应删除或并入有依据段落')
        if not 20<=len(paragraph.text)<=2000:raise ReportPlanningError('叙事段落长度不合规')
        if '\n' in paragraph.text or re.match(r'^\s*(?:[-*]\s|\d+[.)、]\s|#{1,6}\s)',paragraph.text):
            raise ReportPlanningError('正文必须使用独立连贯段落，不能内嵌多段或材料清单')
        if PROCESS.search(paragraph.text) or INTERNAL.search(paragraph.text) or '[[' in paragraph.text:
            raise ReportPlanningError('正文出现处理批次、内部标识或伪造引用标记')
        required=set();source_ids=set()
        for fid in paragraph.claim_ids:
            finding=findings[fid]
            refs=(*finding.supporting_spans,*finding.counter_spans)
            source_ids.update(spans[r].material_id for r in refs)
            # Counter-evidence must follow the statement that it qualifies.
            required.update(cids[spans[r].material_id] for r in finding.counter_spans)
            if finding.supporting_spans and not ({cids[spans[r].material_id] for r in finding.supporting_spans}&set(paragraph.citation_ids)):
                raise ReportPlanningError('主张没有对应支持引用')
            if finding.kind!='observation' and not QUALIFIED.search(paragraph.text):
                raise ReportPlanningError('推断或假设被写成确定事实')
            if finding.counter_spans and not COUNTER_QUALIFIED.search(paragraph.text):
                raise ReportPlanningError('段落隐去了反向材料或限制')
        if not required<=set(paragraph.citation_ids):raise ReportPlanningError('段落遗漏反向材料引用')
        errors=terminology_errors(paragraph.text,[materials[key] for key in source_ids])
        if errors:raise ReportPlanningError('；'.join(errors))
    content='\n\n'.join(p.text+''.join(f'[[{cid}]]' for cid in p.citation_ids) for p in output.paragraphs)
    if chapter.role=='activity':
        times=[findings[key].time_sort_key for key in output.used_claim_ids if findings[key].time_sort_key]
        if times!=sorted(times):raise ReportPlanningError('活动章节偏离已验证的时间顺序')
    if len(chapter.heading)+len(content)>chapter.max_chars:raise ReportPlanningError('章节超过分配的字符预算')
    return output,content

def validate_body(sections,budget):
    errors=[];total=plain_body_chars(sections)
    if not 4<=len(sections)<=6:errors.append('正文必须为4至6章')
    if total>budget.body_hard_chars:errors.append('正文总字符超过硬上限')
    if total<=0:errors.append('正文为空')
    for section in sections:
        if len(section.heading)+len(section.content)>max(1,total)*budget.section_share+1:errors.append('单章占比超过35%：'+section.heading)
        if PROCESS.search(section.heading+'\n'+section.content):errors.append('正文出现批次处理话语')
    if len({s.heading for s in sections})!=len(sections):errors.append('章节标题重复')
    paragraphs=[p.strip() for s in sections for p in s.content.split('\n\n') if len(p.strip())>80]
    normalized=[re.sub(r'\[\[[^\]]+\]\]','',p) for p in paragraphs]
    if len(normalized)!=len(set(normalized)):errors.append('正文出现重复段落')
    if errors:raise ReportPlanningError('；'.join(errors))
    return {'status':'structural_checks_passed','body_chars':total,'section_count':len(sections),
            'max_section_share':max((len(s.heading)+len(s.content))/max(1,total) for s in sections),
            'semantic_support':'需要人工核对；引用合法不等于解释正确'}

def validate_published(organization,sections,appendices,materials,citations):
    validate_body(sections,organization.budget)
    if plain_body_chars(appendices)>organization.budget.appendix_chars:raise ValueError('附录超过预算')
    plan=organization.plan.model_dump(mode='json');checksum=plan.pop('plan_hash')
    if digest(plan)!=checksum:raise ValueError('全局提纲摘要不匹配')
    if tuple(c.heading for c in organization.plan.chapters)!=tuple(s.heading for s in sections):raise ValueError('正文偏离冻结提纲')
    chapter_ids=[c.section_id for c in organization.plan.chapters]
    if len(set(chapter_ids))!=len(chapter_ids) or organization.plan.chapters[0].role!='scope' or sum(c.role=='scope' for c in organization.plan.chapters)!=1:
        raise ValueError('章节标识重复或范围章节位置不合规')
    sources={m.material_id:m for m in materials};known={c.citation_id:c.evidence_key for c in citations}
    if len(known)!=len(citations) or len(sources)!=len(materials):raise ValueError('来源或引用标识重复')
    spans={s.span_id:s for s in organization.spans}
    if len(spans)!=len(organization.spans):raise ValueError('重复来源片段标识')
    for ref in spans.values():
        source=sources.get(ref.material_id)
        if not source or source.evidence_key!=ref.evidence_key or source.source_sha256!=ref.source_sha256 or source.content_sha256!=ref.content_sha256 or source.text[ref.character_start:ref.character_end]!=ref.quote:
            raise ValueError('报告来源片段、位置或哈希不匹配')
    findings={f.finding_id:f for f in organization.findings}
    if len(findings)!=len(organization.findings):raise ValueError('发现标识重复')
    if set(organization.plan.finding_disposition)!=set(findings):raise ValueError('发现覆盖清单不完整')
    used={key for chapter in organization.plan.chapters for key in chapter.finding_ids}
    if not used<=set(findings) or used!={key for key,value in organization.plan.finding_disposition.items() if value=='正文解释'}:
        raise ValueError('全局提纲发现范围不一致')
    for f in findings.values():
        if not set((*f.supporting_spans,*f.counter_spans))<=set(spans):raise ValueError('发现来源超出冻结片段')
        if any(not set(refs)<=set(spans) for refs in f.entity_spans.values()):raise ValueError('主体出现位置超出冻结片段')
    expected={(c.section_id,i) for c,s in zip(organization.plan.chapters,sections) for i,_ in enumerate(s.content.split('\n\n')) if not(c.role=='scope' and i==0)}
    actual={(b.section_id,b.paragraph_index) for b in organization.paragraphs}
    if actual!=expected or len(actual)!=len(organization.paragraphs):raise ValueError('存在没有来源映射的正文段落')
    if hashlib.sha256(sections[0].content.split('\n\n')[0].encode()).hexdigest()!=organization.validation.get('scope_notice_hash'):
        raise ValueError('范围说明与已验证记录不一致')
    for binding in organization.paragraphs:
        chapter=next((c for c in organization.plan.chapters if c.section_id==binding.section_id),None)
        if chapter is None or not set(binding.finding_ids)<=set(chapter.finding_ids):raise ValueError('段落主张不属于所在章节')
        if not set(binding.span_ids)<=set(spans) or not set(binding.citation_ids)<=set(known):raise ValueError('段落引用不在清单中')
        required_spans={r for fid in binding.finding_ids for r in (*findings[fid].supporting_spans,*findings[fid].counter_spans)}
        if not binding.finding_ids or set(binding.span_ids)!=required_spans:raise ValueError('段落来源映射遗漏支持或反向片段')
        section=sections[[c.section_id for c in organization.plan.chapters].index(binding.section_id)]
        paragraphs=section.content.split('\n\n')
        if binding.paragraph_index>=len(paragraphs) or hashlib.sha256(paragraphs[binding.paragraph_index].encode()).hexdigest()!=binding.text_sha256:
            raise ValueError('段落摘要与正文不一致')
        allowed_keys={spans[r].evidence_key for r in binding.span_ids}
        if any(known[cid] not in allowed_keys for cid in binding.citation_ids):raise ValueError('段落引用来源与主张不一致')
        if tuple(re.findall(r'\[\[([^\]]+)\]\]',paragraphs[binding.paragraph_index]))!=binding.citation_ids:raise ValueError('正文引用标记与段落映射不一致')
    # Reconstruct each chapter from the published text and authoritative mappings.
    # Hash-valid metadata alone must not bypass the original claim/citation gate.
    cids={m.material_id:next((cid for cid,key in known.items() if key==m.evidence_key),'') for m in materials}
    if not all(cids.values()):raise ValueError('冻结来源缺少引用标识')
    for chapter,section in zip(organization.plan.chapters,sections):
        mappings=sorted((b for b in organization.paragraphs if b.section_id==chapter.section_id),key=lambda b:b.paragraph_index)
        texts=section.content.split('\n\n')
        paragraphs=[{'text':re.sub(r'\[\[[^\]]+\]\]','',texts[b.paragraph_index]),'claim_ids':list(b.finding_ids),'citation_ids':list(b.citation_ids)} for b in mappings]
        adapter=section_adapter(chapter,findings,spans,sources,cids,'publication',organization.plan.plan_hash)
        output,_=validate_chapter({'section_id':chapter.section_id,'used_claim_ids':[],'paragraphs':paragraphs},chapter,adapter,findings,spans,sources,cids)
        required=set(chapter.required_finding_ids if chapter.required_finding_ids is not None else chapter.finding_ids)
        if not required<=set(output.used_claim_ids):raise ValueError('已发布章节遗漏规划发现')
    if organization.body_chars!=plain_body_chars(sections) or organization.appendix_chars!=plain_body_chars(appendices):raise ValueError('报告字符统计不匹配')
