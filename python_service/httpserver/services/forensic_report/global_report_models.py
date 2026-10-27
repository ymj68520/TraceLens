"""Versioned contracts for organization of one frozen report generation."""
from __future__ import annotations
import hashlib,json
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,model_serializer

PLANNER_VERSION='report-global-plan:v1'
VALIDATION_VERSION='report-global-validation:v1'
PROMPT_VERSION='report-global-writing:v1'

def canonical(value):
    if isinstance(value,BaseModel):value=value.model_dump(mode='json')
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

class FrozenModel(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid')

class ReportExecutionPolicy(FrozenModel):
    version:Literal['report-concurrency-closure:v1']='report-concurrency-closure:v1'
    extraction_concurrency:int=Field(default=4,ge=1,le=4)
    writing_concurrency:int=Field(default=2,ge=1,le=2)
    review_concurrency:int=Field(default=2,ge=1,le=2)
    closure:Literal[True]=True

class ReportBudget(FrozenModel):
    body_target_chars:int=Field(default=12000,ge=800,le=15000)
    body_hard_chars:int=Field(default=20000,ge=1200,le=20000)
    section_share:float=Field(default=0.35,gt=0.25,le=0.35)
    appendix_chars:int=Field(default=200000,ge=1000,le=1000000)
    max_findings:int=Field(default=2000,ge=1,le=10000)
    body_findings:int=Field(default=72,ge=4,le=192)
    max_calls:int=Field(default=512,ge=12,le=4096)
    context_limit:int=Field(default=32768,ge=2048,le=2000000)
    output_tokens:int=Field(default=4096,ge=256,le=16384)
    reserved_tokens:int=Field(default=512,ge=256,le=8192)
    max_tokens:int=Field(default=16777216,ge=4096,le=2**40)
    max_seconds:int=Field(default=1800,ge=30,le=14400)
    image_token_bound:int=Field(default=0,ge=0,le=2000000)
    @model_validator(mode='after')
    def limits(self):
        if self.body_target_chars>self.body_hard_chars:raise ValueError('正文目标超出硬上限')
        if self.output_tokens+self.reserved_tokens>=self.context_limit:raise ValueError('报告请求没有输入空间')
        return self

class SourceQuote(FrozenModel):
    material_id:str
    quote:str=Field(min_length=1,max_length=300)
    character_start:int|None=Field(default=None,ge=0)

class FindingSuggestion(FrozenModel):
    statement:str=Field(min_length=4,max_length=600)
    kind:Literal['observation','inference','hypothesis']
    topic:Literal['environment','identity','activity','business','connections','limitations']
    entities:tuple[str,...]=Field(default=(),max_length=8)
    action:str=Field(default='',max_length=100)
    time_text:str=Field(default='',max_length=100)
    time_basis:Literal['record_time','document_time','file_metadata','unknown']='unknown'
    supporting_refs:tuple[SourceQuote,...]=Field(default=(),max_length=6)
    counter_refs:tuple[SourceQuote,...]=Field(default=(),max_length=6)
    limitations:tuple[str,...]=Field(default=(),max_length=8)
    alternatives:tuple[str,...]=Field(default=(),max_length=6)
    priority_hint:Literal['P1','P2','P3','unassessed']='unassessed'
    case_context_quote:str=Field(default='',max_length=300)

class FindingBatch(FrozenModel):
    findings:tuple[FindingSuggestion,...]=Field(default=(),max_length=20)

class FrozenSpan(FrozenModel):
    span_id:str
    material_id:str
    evidence_key:str
    source_sha256:str
    content_sha256:str
    character_start:int=Field(ge=0)
    character_end:int=Field(gt=0)
    quote:str=Field(min_length=1,max_length=300)
    position_resolution:str|None=None
    @model_serializer(mode='wrap')
    def compatible_position(self,handler):
        value=handler(self)
        if self.position_resolution is None:value.pop('position_resolution',None)
        return value

class ReportFinding(FrozenModel):
    finding_id:str
    statement:str
    kind:Literal['observation','inference','hypothesis']
    topic:str
    entities:tuple[str,...]=()
    action:str=''
    time_text:str=''
    time_basis:str='unknown'
    time_sort_key:str|None=None
    supporting_spans:tuple[str,...]=()
    counter_spans:tuple[str,...]=()
    limitations:tuple[str,...]=()
    alternatives:tuple[str,...]=()
    priority_hint:str='unassessed'
    case_context_quote:str=''
    source_finding_ids:tuple[str,...]=()
    entity_spans:dict[str,tuple[str,...]]=Field(default_factory=dict)
    @model_serializer(mode='wrap')
    def legacy_entity_spans(self,handler):
        value=handler(self)
        if not self.entity_spans:value.pop('entity_spans',None)
        return value

class ReportConflict(FrozenModel):
    conflict_id:str
    finding_ids:tuple[str,...]
    explanation:str
    status:Literal['unresolved']='unresolved'

class PlannedChapter(FrozenModel):
    section_id:str
    role:Literal['scope','environment','activity','connections','limitations','conclusion']
    heading:str=Field(min_length=2,max_length=40)
    brief:str
    finding_ids:tuple[str,...]=()
    required_finding_ids:tuple[str,...]|None=None
    target_chars:int=Field(ge=80)
    max_chars:int=Field(ge=120)
    @model_validator(mode='after')
    def required_scope(self):
        if self.required_finding_ids is not None:
            if self.role not in ('scope','conclusion') or not self.required_finding_ids or not set(self.required_finding_ids)<=set(self.finding_ids):
                raise ValueError('收束章节必需发现超出允许范围')
        return self
    @model_serializer(mode='wrap')
    def compatible_required(self,handler):
        value=handler(self)
        if self.required_finding_ids is None:value.pop('required_finding_ids',None)
        return value

class GlobalReportPlan(FrozenModel):
    version:Literal['report-global-plan:v1']=PLANNER_VERSION
    main_thread:str
    chapters:tuple[PlannedChapter,...]=Field(min_length=4,max_length=6)
    finding_disposition:dict[str,str]
    plan_hash:str

class ParagraphBinding(FrozenModel):
    section_id:str
    paragraph_index:int
    text_sha256:str
    finding_ids:tuple[str,...]
    citation_ids:tuple[str,...]
    span_ids:tuple[str,...]

class ReportOrganization(FrozenModel):
    planner_version:Literal['report-global-plan:v1']=PLANNER_VERSION
    validation_version:Literal['report-global-validation:v1']=VALIDATION_VERSION
    quality:Literal['review_required','preliminary']
    quality_message:str
    plan:GlobalReportPlan
    findings:tuple[ReportFinding,...]
    spans:tuple[FrozenSpan,...]
    conflicts:tuple[ReportConflict,...]=()
    paragraphs:tuple[ParagraphBinding,...]
    coverage:tuple[dict[str,Any],...]
    warnings:tuple[str,...]=()
    budget:ReportBudget
    usage:dict[str,int|str]
    body_chars:int
    appendix_chars:int
    validation:dict[str,Any]
    artifact_digests:dict[str,str]=Field(default_factory=dict)
