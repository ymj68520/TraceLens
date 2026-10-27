import asyncio
from types import SimpleNamespace
import httpx
import pytest
from test_report_concurrency import input9,admitted
from httpserver.services.forensic_report.global_report_store import PlanningStore,BudgetedReportProvider,ReportPlanningError
from httpserver.services.forensic_report.report_transport import Cooldown,retry_delay


def error(code=429,headers=None):
    request=httpx.Request('POST','https://example.invalid/model')
    return httpx.HTTPStatusError('provider error',request=request,response=httpx.Response(code,request=request,headers=headers))


@pytest.mark.asyncio
async def test_cooldown_honors_the_latest_deadline_in_bounded_sleeps():
    now=[0.0];waits=[]
    async def sleep(seconds):waits.append(seconds);now[0]+=seconds
    cooldown=Cooldown(clock=lambda:now[0],sleep=sleep)
    cooldown.defer(30);cooldown.defer(65);await cooldown.wait()
    assert waits==[30,30,5] and now[0]==65


def test_provider_retry_after_is_honored_and_invalid_values_are_safe():
    assert retry_delay(error(headers={'Retry-After':'90'}).response,0)==90
    for value in ('invalid','nan','inf','-1'):
        assert retry_delay(error(headers={'Retry-After':value}).response,1)==60


@pytest.mark.asyncio
@pytest.mark.parametrize('maximum,failures,expected_calls', [(3,1,2),(2,5,2),(8,5,3)])
async def test_rate_limit_retries_charge_each_call_and_stop_at_the_budget(tmp_path,monkeypatch,maximum,failures,expected_calls):
    from httpserver.services.forensic_report import report_transport
    waits=[]
    async def wait():pass
    monkeypatch.setattr(report_transport,'report_cooldown',lambda:SimpleNamespace(wait=wait,defer=waits.append))
    value=input9(max_calls=12,max_tokens=100000);repo,row=admitted(tmp_path,value);repo.claim_generation(row.generation_id)
    store=PlanningStore(repo.db_path,row.generation_id,row.input_hash,value.report_budget)
    precharged=12-maximum
    for _ in range(precharged):store.reserve('extraction',10,10)
    class Model:
        calls=0
        async def chat_completion(self,*args,**kwargs):
            self.calls+=1
            if self.calls<=failures:raise error()
            return {'content':'{"ok":true}','model':'test-model'}
    model=Model();provider=BudgetedReportProvider(model,store,value.execution_policy);provider.retry_rate_limits=True
    if failures==1:assert await provider.call('chapter','test','test',{},output=10)=={'ok':True}
    else:
        with pytest.raises((httpx.HTTPStatusError,ReportPlanningError)):
            await provider.call('chapter','test','test',{},output=10)
    assert model.calls==expected_calls and store.usage()['calls']==precharged+expected_calls
    assert not any(provider.active.values())
    assert waits==([30] if failures==1 else [30,60])


@pytest.mark.asyncio
async def test_authentication_failure_is_not_retried(tmp_path):
    value=input9(max_calls=12);repo,row=admitted(tmp_path,value);repo.claim_generation(row.generation_id)
    store=PlanningStore(repo.db_path,row.generation_id,row.input_hash,value.report_budget)
    class Model:
        async def chat_completion(self,*args,**kwargs):raise error(401)
    provider=BudgetedReportProvider(Model(),store,value.execution_policy);provider.retry_rate_limits=True
    with pytest.raises(httpx.HTTPStatusError):await provider.call('chapter','auth','test',{},output=10)
    assert store.usage()['calls']==1
