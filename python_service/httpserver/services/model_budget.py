"""Final-message admission and durable per-attempt file-phase budgets.

UTF-8 serialized byte counts are a conservative bound for the byte-BPE model
adapters used here, never a chars/4 token estimate. Actual usage is not used to
refund uncertain/failed calls, so retries cannot overspend reserved capacity.
"""
from __future__ import annotations
import json
import sqlite3
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_context=ContextVar('file_model_budget',default=None)
_active_plan=ContextVar('active_selection_plan',default=None)
_transport_budgeted=ContextVar('transport_budgeted_attempt',default=False)


@contextmanager
def budgeted_transport_attempt():
    """The caller owns dispatch accounting and retries; forbid hidden retries."""
    token=_transport_budgeted.set(True)
    try:yield
    finally:_transport_budgeted.reset(token)


def transport_attempt_is_budgeted():
    return _transport_budgeted.get()


@contextmanager
def selection_run(plan_id):
    if not plan_id:
        yield
        return
    token=_active_plan.set(plan_id)
    try:yield
    finally:_active_plan.reset(token)


def current_selection_run():
    return _active_plan.get()


class ModelBudgetError(ValueError):
    pass


def serialized_bound(messages):
    return len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode('utf-8'))


def prepare_text_request(settings,system,content,instruction=None,max_tokens=None):
    from ..prompts import TEXT_ANALYSIS_USER_TEMPLATE,TEXT_ANALYSIS_USER_WITH_INSTRUCTION_TEMPLATE
    context=int(getattr(settings,'llm_context_length',4096))
    reserve=int(getattr(settings,'llm_reserved_tokens',512))
    requested=int(max_tokens if max_tokens is not None else getattr(settings,'llm_text_max_tokens',2048))
    if context<=reserve+32 or requested<=0:raise ModelBudgetError('模型上下文或输出预算无效')
    # max_tokens is an upper limit, not an obligation to fill the response window.
    output=min(requested,(context-reserve)//2)
    content=content or '';instruction=instruction or ''
    if len(content)>256 and content in instruction:
        instruction=instruction.replace(content,'（文件正文见本次请求的材料部分）')
    def messages(value):
        user=(TEXT_ANALYSIS_USER_WITH_INSTRUCTION_TEMPLATE.format(content=value,instruction=instruction)
              if instruction else TEXT_ANALYSIS_USER_TEMPLATE.format(content=value))
        return [{'role':'system','content':system},{'role':'user','content':user}]
    available=context-output-reserve
    if serialized_bound(messages(''))>available:
        raise ModelBudgetError('调查要求或系统提示已超出上下文预算，未发送请求')
    raw=content.encode('utf-8')
    low,high=0,len(raw)
    while low<high:
        middle=(low+high+1)//2
        text=raw[:middle].decode('utf-8',errors='ignore')
        if middle<len(raw):text+='\n（材料受本次上下文预算限制，以下未读取部分不作推断。）'
        if serialized_bound(messages(text))<=available:low=middle
        else:high=middle-1
    value=raw[:low].decode('utf-8',errors='ignore')
    if low<len(raw):value+='\n（材料受本次上下文预算限制，以下未读取部分不作推断。）'
    result=messages(value)
    if serialized_bound(result)+output+reserve>context:raise ModelBudgetError('完整请求超出上下文预算')
    return result,output,{'input_upper_bound':serialized_bound(result)+reserve,'output_limit':output,
        'context_limit':context,'accounting':'utf8_byte_bpe_upper_bound','content_truncated':low<len(raw)}


@contextmanager
def analysis_budget(database,reference,plan_id=None,task_id=None):
    """Only plans containing this source can authorize a phase budget."""
    plan_id=plan_id or _active_plan.get()
    selected=None
    if database and Path(database).is_file():
        with sqlite3.connect(database,timeout=10) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='selection_runs'").fetchone():
                query='SELECT plan_id,plan_json FROM selection_runs'
                rows=db.execute(query+' WHERE plan_id=?',(plan_id,)) if plan_id else db.execute(query+' ORDER BY created_at DESC,rowid DESC')
                for key,raw in rows:
                    plan=json.loads(raw)
                    if str(plan.get('policy_version','')).startswith('candidate-selection:'):
                        verified=dict(plan);digest=verified.pop('plan_digest',None)
                        actual=hashlib.sha256(json.dumps(verified,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                        if actual!=digest:raise ModelBudgetError('选择计划完整性校验失败，未发送模型请求')
                    matches=[item for item in plan.get('selected',[]) if item.get('reference')==reference and (not task_id or item.get('task_id')==task_id)]
                    if len(matches)==1:
                        selected=(plan.get('budget_database') or str(database),key,matches[0].get('source_key',reference));break
    if plan_id and selected is None:raise ModelBudgetError('分析来源不在指定选择计划中')
    token=_context.set(selected)
    try:yield selected
    finally:_context.reset(token)


def reserve_attempt(input_bound,output_limit):
    scope=_context.get()
    if not scope:return
    database,plan,source=scope
    with sqlite3.connect(database,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        amount=int(input_bound)+int(output_limit)
        cursor=db.execute('UPDATE selection_budget SET used_calls=used_calls+1,reserved_tokens=reserved_tokens+? '
            'WHERE plan_id=? AND used_calls<max_calls AND reserved_tokens+?<=max_tokens',(amount,plan,amount))
        if cursor.rowcount!=1:raise ModelBudgetError('本轮模型调用或令牌预算已用尽，未发送请求')
        db.execute("INSERT INTO selection_call_ledger(plan_id,source_key,input_bound,output_limit,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                   (plan,source,int(input_bound),int(output_limit)))


def reserve_vision_attempt(settings,text,image_count,output=2048):
    if _context.get() is None:return output
    bound=int(getattr(settings,'llm_vision_image_token_bound',0) or 0)
    if bound<=0:raise ModelBudgetError('本轮尚未配置多模态令牌计数上界，未发送图像请求')
    context=int(getattr(settings,'llm_context_length',4096));reserve=int(getattr(settings,'llm_reserved_tokens',512))
    output=min(output,max(1,(context-reserve)//2))
    estimate=len(text.encode('utf-8'))+image_count*bound+reserve
    if estimate+output>context:raise ModelBudgetError('图像及文本完整请求超出上下文预算')
    reserve_attempt(estimate,output);return output


def mark_finished(database,reference,state='completed',error=''):
    scope=_context.get()
    if not scope:return
    with sqlite3.connect(scope[0],timeout=10) as db:
        db.execute("INSERT INTO selection_execution VALUES(?,?,?,strftime('%s','now'),?) ON CONFLICT(plan_id,source_key) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,error=excluded.error",
                   (scope[1],scope[2],state,error))


def plan_allows_cached_analysis(database,reference,task_id=None):
    with analysis_budget(database,reference,task_id=task_id) as scope:
        if scope is None:return True  # Legacy runs keep their existing accessor contract.
        with sqlite3.connect(scope[0],timeout=10) as db:
            return db.execute("SELECT 1 FROM selection_execution WHERE plan_id=? AND source_key=? AND state='completed'",scope[1:]).fetchone() is not None
