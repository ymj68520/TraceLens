// Browser-only fixture entry. Not included in the production index or routes.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import ForensicReportPage from '../pages/ForensicReportPage';
import IngestionQualityPanel from '../components/knowledge-graph/IngestionQualityPanel';
import '../styles/index.css';

const scenario = new URLSearchParams(location.search).get('scenario') || 'new';
const old = scenario === 'old';
const status = scenario === 'running' ? 'generating' : scenario === 'failed' ? 'failed' : 'ready';
const version = { report_id:'qa-report',version:2,status,progress:33,stage:'running',title:'交付验收样本报告',report_kind:'llm_generation',error:'global_report_blocked' };
const versions = scenario === 'empty' ? [] : [version];
const material = {material_id:'m0001',evidence_key:'file:/case/配置.txt',kind:'text',text:'配置中记录账号甲，尚不能确认使用行为。',source_sha256:'a'.repeat(64),content_sha256:'b'.repeat(64),status:'ready',limitations:[]};
const quality = old ? {status:'unassessed',label:'历史版本未评估',reasons:['旧版没有当前质量账本。']} : {
  status: scenario === 'limited' ? 'limited' : 'passed',label:scenario === 'limited' ? '有范围限制' : '来源与结构校验通过',
  reasons:scenario === 'limited' ? ['本轮仍有材料未完成读取，不能认定没有相关活动。'] : ['机器校验不代替对关键结论的人工复核。'],
  counts:{sources:1,extracted:scenario==='limited'?0:1,partial:scenario==='limited'?1:0,deferred:0,unavailable:0},scope:'当前报告冻结版本；不代表整盘材料'};
const sections=['研判范围与主要发现','关键活动及时间顺序','矛盾与未决事项','结论与后续核查'].map((heading,i)=>({heading,content:`${heading}依据冻结配置观察展开，账号是否实际使用仍需其他来源核对。[[c0001]]`,citation_ids:['c0001']}));
const report={...version,task_id:'qa-task',generation_id:'qa-generation',created_at:'2026-10-26T00:00:00Z',title:version.title,
  sections:old?[{heading:'历史材料',content:'原始证据：Original English evidence.',citation_ids:['c0001']}]:sections,
  citations:[{citation_id:'c0001',evidence_key:material.evidence_key}],quality,
  stage_analysis:old?null:{analysis_mode:'evidence_only',materials:[material],directions:[],warnings:[],comparisons:[]},
  organization:old?null:{quality:scenario==='limited'?'preliminary':'review_required',quality_message:'本样本用于页面状态验收。',
    body_chars:300,appendix_chars:40,plan:{chapters:sections, finding_disposition:{}},validation:{max_section_share:0.25},usage:{calls:8},budget:{max_calls:12},warnings:[],findings:[],coverage:[],spans:[]},appendices:[]};
const dataSource={listVersions:async()=>versions,getStatus:async()=>version,search:async()=>({hits:[],total:0}),getManifest:async()=>null};
createRoot(document.getElementById('root')).render(<MemoryRouter><main className="mx-auto max-w-6xl p-6">
  <p className="mb-4 text-sm text-slate-500">合成界面验收 · 不调用模型</p>
  <ForensicReportPage scopeType="task" scopeId="qa-task" dataSource={dataSource} narrativeLoader={async()=>report}/>
  {scenario==='limited' && <IngestionQualityPanel job={{task_id:'qa-task',job_id:'qa-job',status:'COMPLETED',quality:{label:'有范围限制',status:'limited',total:909,successful:908,failed:1,unprocessed:0,retryable:true,reasons:['1 条摄取未成功。']}}} onRetry={()=>{document.body.dataset.retry='clicked';}}/>}
</main></MemoryRouter>);
