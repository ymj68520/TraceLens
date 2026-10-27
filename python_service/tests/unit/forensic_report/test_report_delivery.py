import hashlib, io, json, re, sqlite3, zipfile
from html.parser import HTMLParser
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_global_report import envelope, admitted, Model
from test_report_narrative_routes import _publish
from httpserver.routes import investigation_workbench, report_generation
from httpserver.services.forensic_report.generation_execution import ReportGenerationExecutor
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.models import GenerationReportManifest
from httpserver.services.forensic_report.offline_delivery import offline_files, offline_archive, projection, render
from httpserver.services.forensic_report.report_quality import report_quality
from httpserver.services.forensic_report.narrative_reader import read_narrative_version_strict
from httpserver.services.evidence.exceptions import EvidenceStoreError

async def published(root):
    value=envelope();repo,row=admitted(root,value);writer=GenerationReportWriter(root)
    await ReportGenerationExecutor(repo,writer,Model())._execute(row.generation_id)
    done=repo.get_generation_input(row.generation_id)
    assert done.status=='completed', done.error_message
    return repo,done,GenerationReportManifest.model_validate(writer.read_manifest('task',done.report_id))

class Links(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.hrefs=[];self.scripts=[];self.external=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.ids.append(attrs['id'])
        if attrs.get('href'):self.hrefs.append(attrs['href'])
        if tag=='script' or any(k.startswith('on') for k in attrs):self.scripts.append(tag)
        if attrs.get('src'):self.external.append(attrs['src'])

@pytest.mark.asyncio
async def test_offline_archive_has_complete_links_hashes_and_immutable_versions(tmp_path):
    repo,row,manifest=await published(tmp_path)
    files=offline_files(manifest,1);links=Links();links.feed(files['report.html'].decode())
    assert links.hrefs and all(h[1:] in links.ids for h in links.hrefs)
    assert len(links.ids)==len(set(links.ids)) and not links.scripts and not links.external
    index=json.loads(files['manifest.json'])
    for name,item in index['files'].items():assert hashlib.sha256(files[name]).hexdigest()==item['sha256']
    for source in json.loads(files['sources.json']):
        assert hashlib.sha256(source['text'].encode()).hexdigest()==source['content_sha256']
        for span in source['spans']:assert source['text'][span['character_start']:span['character_end']]==span['quote']
    assert b'media_base64' not in files['sources.json']
    first,h=offline_archive(manifest,1,tmp_path);again,h2=offline_archive(manifest,1,tmp_path)
    assert first==again and h==h2
    with zipfile.ZipFile(io.BytesIO(first)) as archive:assert set(archive.namelist())==set(files)
    _,row2,next_manifest=await published(tmp_path)
    second,_=offline_archive(next_manifest,2,tmp_path)
    assert first!=second and len(list((tmp_path/'exports').glob('**/*.zip')))==2
    assert report_quality(manifest).status in ('passed','limited')

def test_legacy_export_preserves_english_evidence_and_blocks_active_markup(tmp_path):
    repo,rid,gid=_publish(tmp_path)
    manifest=GenerationReportManifest.model_validate(GenerationReportWriter(tmp_path).read_manifest('task-A',rid))
    raw=manifest.model_dump(mode='json');raw['title']='<img src=x onerror=alert(1)>'
    raw['sections'][0]['content']='Original English evidence <script>alert(1)</script> ![x](https://example.invalid/x)'
    manifest=GenerationReportManifest.model_validate(raw)
    view=projection(manifest,2);markup=render(view);links=Links();links.feed(markup)
    assert not links.scripts and not links.external and 'Original English evidence' in markup
    assert '&lt;script&gt;' in markup and '未记录' in markup and '历史版本未评估' in markup
    assert '#source-1' in links.hrefs and all(h[1:] in links.ids for h in links.hrefs)
    markdown=render(view,False);assert '![x](' not in markdown and '<script>' not in markdown

@pytest.mark.asyncio
async def test_delivery_routes_enforce_scope_and_reject_tampered_snapshot(tmp_path,monkeypatch):
    repo,row,manifest=await published(tmp_path)
    monkeypatch.setattr(report_generation,'_report_root',lambda:tmp_path)
    async def strict(task_id,report_id):
        result=read_narrative_version_strict(tmp_path/'reports.db',tmp_path,task_id,report_id)
        if result is None:
            from httpserver.services.evidence.exceptions import EvidenceNotFoundError
            raise EvidenceNotFoundError('report not found')
        return result
    monkeypatch.setattr(investigation_workbench,'_strict_report',strict)
    from types import SimpleNamespace
    monkeypatch.setattr(investigation_workbench,'get_settings',lambda:SimpleNamespace(report_output_dir=str(tmp_path)))
    app=FastAPI();app.include_router(investigation_workbench.router,prefix='/workbench')
    client=TestClient(app);base=f'/workbench/task/final-reports/{row.report_id}'
    for suffix in ('html','markdown','print','offline'):
        assert client.get(base+'/'+suffix).status_code==200
        assert client.get(base.replace('/task/','/foreign/')+'/'+suffix).status_code==404
    status=report_generation._status_response(row,include_report=True)
    assert status.quality.status in ('passed','limited') and status.status=='completed'
    file=GenerationReportWriter(tmp_path).final_dir('task',row.report_id)/'manifest.json'
    file.write_bytes(file.read_bytes().replace('材料'.encode(),'伪造'.encode(),1))
    assert client.get(base+'/offline').status_code==503
    with pytest.raises(Exception) as error:report_generation._status_response(row,include_report=True)
    assert error.value.status_code==503

def test_execution_failure_and_missing_quality_are_not_success():
    assert report_quality(execution_status='running').status=='pending'
    assert report_quality(execution_status='failed',error_code='global_report_blocked').status=='failed'

@pytest.mark.asyncio
async def test_english_new_narrative_is_rejected_while_evidence_is_untouched(tmp_path):
    class English(Model):
        async def chat_completion(self,system,prompt,**kwargs):
            response=await super().chat_completion(system,prompt,**kwargs)
            body=json.loads(response['content'])
            if body.get('paragraphs'):
                for p in body['paragraphs']:p['text']='This is an English model narrative that must not be published as a Chinese report.'
                response['content']=json.dumps(body)
            return response
    value=envelope();repo,row=admitted(tmp_path,value)
    await ReportGenerationExecutor(repo,GenerationReportWriter(tmp_path),English())._execute(row.generation_id)
    result=repo.get_generation_input(row.generation_id)
    assert result.status=='failed' and '中文' in result.error_message and result.report_id is None
