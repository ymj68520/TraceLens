"""Bounded visual projection and auxiliary review; never replace source checks."""
import asyncio,base64,hashlib
from .global_report_models import canonical
from .global_report_store import ReportPlanningError
from .generation_sources import material
from .generation_prompts import NEUTRAL_IMAGE_PROMPT_V1
from ...prompts import VISION_ANALYSIS_SYSTEM

REVIEW_PROMPT='''核对给定段落是否与本轮发现及其支持/反向原文存在明显冲突。不要引入外部事实或重写证据。
重点检查：把配置/缓存说成实际行为，把推断写成确定事实，隐去反向片段，已知时间顺序颠倒，主体混淆，凭合法引用声称已核实犯罪。
只返回JSON {"issues":[{"paragraph_index":0,"quote":"段落中有问题的原句片段（至少8字）","reason":"为什么给定来源不足以支持该表述"}]}。没有明确问题时issues为空；谨慎区分措辞不喜欢与证据不支持。此复核仅辅助人工，不等于事实认证。'''

async def project_materials(envelope,provider):
    if envelope.baseline:
        from .generation_stages import validate_materialized_sources
        validate_materialized_sources(envelope.neutral_materials,envelope.baseline.materials)
        return envelope.baseline.materials,[]
    output=[];warnings=[]
    for source in envelope.neutral_materials:
        if source.kind!='image':output.append(source);continue
        budget=provider.store.budget
        try:
            if not budget.image_token_bound:raise ReportPlanningError('视觉模型令牌上界未配置')
            # Existing FileAnalyzer.analyze_image uses a fixed 2048 output cap.
            # Reserve its actual system+user text and configured image upper bound.
            bound=len(canonical([{'role':'system','content':VISION_ANALYSIS_SYSTEM},{'role':'user','content':NEUTRAL_IMAGE_PROMPT_V1}]).encode())+budget.image_token_bound+budget.reserved_tokens
            vision_output=2048
            if bound+vision_output>budget.context_limit:raise ReportPlanningError('图像请求超出上下文预算')
            provider.store.save('visual_request',source.material_id,{'source_sha256':source.source_sha256,'input_bound':bound})
            provider.store.reserve('visual',bound,vision_output)
            remaining=max(1,budget.max_seconds-provider.store.usage()['elapsed_seconds'])
            response=await asyncio.wait_for(provider.delegate.analyze_image(image_data=base64.b64decode(source.media_base64),prompt=NEUTRAL_IMAGE_PROMPT_V1),timeout=remaining)
            provider.store.save('visual_response',source.material_id,response)
            text=(response.get('analysis') or {}).get('description') or ''
            if not text.strip() or response.get('success') is False:raise ReportPlanningError('没有有效图像观察')
            if response.get('model'):provider.models.add(response['model'])
            output.append(material(source.material_id,source.evidence_key,kind='machine_visual',text=text,
                source_hash=source.source_sha256,status='partial',limitations=(*source.limitations,'机器视觉观察不是原文或逐字OCR，需人工核对')))
        except Exception as exc:
            provider.store.save('visual_failure',source.material_id,{'reason':str(exc)[:200]})
            output.append(material(source.material_id,source.evidence_key,source_hash=source.source_sha256,
                limitations=(*source.limitations,'本轮图像观察未完成，未把元数据当正文')))
            warnings.append('本轮存在未完成的图像观察')
    return tuple(output),warnings

async def review_chapter(chapter,draft,request,provider,attempt=0):
    payload={'operation':'semantic_review','section_id':chapter.section_id,
             'claims':request['claims'],'paragraphs':[p.text for p in draft.paragraphs]}
    if 'source_records' in request:
        payload['source_records']=request['source_records']
        payload['source_record_policy']=request['source_record_policy']
        payload['review_policy']='核对字段时同时检查冻结原记录，不能因短引文未包含某字段就判为没有来源。合理的限制性表述不是新增肯定事实。只返回必须修正的明确证据问题，编辑偏好不列为问题。'
    if not provider.fits(REVIEW_PROMPT,payload,output=min(1024,provider.output_limit)):
        return None,'章节复核超过上下文额度，关键结论需人工复核'
    try:
        raw=await provider.call('semantic_review',f'{chapter.section_id}:{attempt}',REVIEW_PROMPT,payload,output=min(1024,provider.output_limit))
        issues=raw.get('issues')
        if not isinstance(issues,list) or len(issues)>12:raise ValueError('复核协议无效')
        result=[]
        for issue in issues:
            index=issue.get('paragraph_index');quote=issue.get('quote');reason=issue.get('reason')
            if type(index) is not int or not 0<=index<len(draft.paragraphs) or not isinstance(quote,str) or len(quote)<8 or quote not in draft.paragraphs[index].text or not isinstance(reason,str) or not reason.strip():
                raise ValueError('复核意见没有指向实际段落')
            result.append({'paragraph_index':index,'quote':quote,'reason':reason[:300]})
        if request.get('grounded_review') and result:
            from .grounded_review import resolve_issues
            paragraphs={('',i):{'text':p.text,'citation_ids':p.citation_ids} for i,p in enumerate(draft.paragraphs)}
            return await resolve_issues(result,paragraphs,request['source_records'],provider,f'chapter:{chapter.section_id}:{attempt}',
                                        protocol=request.get('grounded_review_protocol',1))
        return result,None
    except (ValueError,KeyError,TypeError,asyncio.TimeoutError):return None,'辅助模型复核未完成，不能视作解释已被验证'
