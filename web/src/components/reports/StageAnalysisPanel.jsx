import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import { investigationEvidenceUrl } from '../../utils/evidenceKey';
import { priorityStyle } from './evidenceClassificationStyles';

const STATUS = { supported: '原判断得到支持', revised: '原判断需要修正', weakened: '支持减弱',
    contradicted: '存在相反材料', insufficient: '依据不足', case_only: '仅由案情提出' };
const KIND = { text: '冻结文本片段', parsed_text: '冻结解析片段', android_record: 'Android派生记录',
    audio_transcript: '机器转写片段', machine_visual: '机器视觉观察（非原文或OCR）', unavailable: '来源暂不可读' };
const ORIGIN = { material: '材料自主发现', reinterpreted: '关联首次判断', new_candidate: '新增关注候选', case_only: '仅案情提出，尚无材料支持' };
const LIMITS = {
    FIRST_4000_PARSED_CHARACTERS_ONLY: '仅冻结前4000个解析字符，非全文分析',
    ORIGINAL_HASH_UNAVAILABLE: '原记录未提供可核对的原始哈希',
    DERIVED_RECORD_NOT_ORIGINAL_DATABASE_ROW: '派生解析记录，不代表已核对原始数据库行',
    MACHINE_TRANSCRIPT_NOT_VERIFIED_SPEECH: '机器转写，尚需核对音频原文',
    PARTIAL_TRANSCRIPT: '转写覆盖不完整',
    MACHINE_VISUAL_NOT_ORIGINAL_TEXT: '机器视觉观察，不能视为原文或已核验事实',
    NEUTRAL_VISUAL_FAILED: '本轮图像中立读取失败',
    TEXT_ENCODING_INFERRED_GB18030: '文本采用推定的GB18030编码解码',
    SQLITE_SCHEMA_AND_FIRST_50_ROWS_ONLY: '数据库仅读取结构与每表前50行样本',
    COMPANION_WAL_NOT_READ: '未读取配套WAL文件，不能视为完整数据库取证',
};
function sourceLabel(code) {
    return LIMITS[code] || '本项来源未完整读取或尚需核查';
}

function Quotes({ label, refs = [], onOpenMaterial }) {
    return refs.length > 0 && <div className="space-y-2">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
        {refs.map((ref, index) => <blockquote key={`${ref.material_id}-${index}`} className="border-l-2 border-slate-300 pl-3 text-sm leading-6">
            {ref.quote}
            {ref.ambiguous && <span className="ml-1 text-xs text-slate-500">（冻结文本中有多处匹配）</span>}
            <button type="button" className="ml-2 text-xs text-blue-700 dark:text-blue-300"
                onClick={() => onOpenMaterial(ref.material_id)}>查看 {ref.material_id} 冻结材料</button>
        </blockquote>)}
    </div>;
}

export function StageSourcePanel({ material, citationId, taskId, reportId, onClose }) {
    const url = material && investigationEvidenceUrl(taskId, material.evidence_key, { reportId, citationId });
    return <section className="space-y-4 text-slate-700 dark:text-slate-200" aria-label="本轮冻结材料溯源">
        <div className="flex items-center justify-between">
            <h3 className="font-semibold">{citationId} · 本轮冻结材料</h3>
            <button type="button" aria-label="关闭溯源面板" onClick={onClose}><X size={18} /></button>
        </div>
        {!material ? <p>本轮没有对应的冻结材料，不回退展示旧 AI 摘要。</p> : <>
            <p className="break-all text-xs">{material.evidence_key}</p>
            <p className="text-sm">{KIND[material.kind] || '来源类型未知'} · {material.status === 'unavailable' ? '不可用' : material.status === 'partial' ? '部分可用' : '已冻结'}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">使用本报告生成时的材料，不随后续任务案情或旧分析变化。</p>
            <dl className="space-y-2 break-all text-xs">
                <dt>来源 SHA-256（文件字节或派生记录）</dt><dd className="font-mono">{material.source_sha256 || '原始来源不可用'}</dd>
                <dt>本轮冻结文本 SHA-256</dt><dd className="font-mono">{material.content_sha256}</dd>
                <dt>读取范围</dt><dd>{material.kind === 'machine_visual'
                    ? `机器视觉描述 ${Array.from(material.text || '').length} 字符，不代表已读取图像全部文字。`
                    : `${Array.from(material.text || '').length} / ${material.original_characters || 0} 字符；引文位置为本轮冻结文本的 Unicode 字符位置，非磁盘偏移。`}</dd>
            </dl>
            {material.limitations?.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs text-amber-800 dark:text-amber-300">
                {material.limitations.map(code => <li key={code}>{sourceLabel(code)}</li>)}
            </ul>}
            <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-white p-4 text-sm leading-7 dark:border-slate-700 dark:bg-slate-800">{material.text || '本次没有可用内容。历史 AI 摘要未作为替代输入。'}</pre>
            {url && <Link className="text-sm text-blue-700 dark:text-blue-300" to={url}>前往原证据与时间线</Link>}
        </>}
    </section>;
}

export default function StageAnalysisPanel({ stage, taskId, classifications, onOpenMaterial }) {
    if (!stage) return null;
    const guided = stage.analysis_mode === 'case_guided';
    const baselineById = new Map((stage.baseline_directions || []).map(d => [d.direction_id, d]));
    const available = stage.materials.filter(m => m.status !== 'unavailable' && m.text).length;
    const changed = (classifications?.items || []).filter(c => stage.baseline_priorities?.[c.evidence_key]
        && stage.baseline_priorities[c.evidence_key] !== c.priority);
    return <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200" data-testid="stage-analysis">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">{guided ? '二次研判与首次判断对照' : '首次自主研判 · 材料发现'}</h3>
            {guided && <Link data-testid="baseline-report-link" className="text-sm text-blue-700 dark:text-blue-300"
                to={`/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic&report_id=${encodeURIComponent(stage.baseline_report_id)}`}>查看首次报告 ↗</Link>}
        </div>
        <p className="text-sm leading-7">{guided
            ? '本轮沿用首次报告的同一批冻结材料，没有新增证据。案情是调查语境，首次模型判断不是独立证据。'
            : '本轮未使用案情描述、人工备注、历史 AI 摘要或已接受分析。范围限于当前入报且可读取的材料，材料选择本身不代表全镜像覆盖。'}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">材料 {stage.materials.length} 份 · 可用 {available} 份 · 不可用 {stage.materials.length - available} 份 · {stage.warnings?.length || 0} 项分析或读取限制</p>
        {stage.warnings?.includes('TEXT_MODEL_CHANGED_OR_BASELINE_MODEL_UNKNOWN') && <p className="text-xs text-amber-800 dark:text-amber-300">
            两轮文本模型记录不同或首次模型信息不足，判断差异不能全部归因于案情变化。
            首次：{stage.baseline_text_models?.join('、') || '未知'}；本轮：{stage.text_models?.join('、') || '未知'}。
        </p>}
        {guided && <details><summary className="cursor-pointer text-sm">查看本次冻结案情</summary>
            <p className="mt-3 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-7 dark:bg-slate-900">{stage.case_description}</p>
        </details>}
        <details open><summary className="cursor-pointer text-sm font-medium">本轮调查方向与其他解释 · {stage.directions.length} 项</summary>
            <div className="mt-3 max-h-[40rem] space-y-4 overflow-auto">
                {stage.directions.map(direction => <article key={direction.direction_id} className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-600">
                    <p className="text-xs text-slate-500 dark:text-slate-400">{ORIGIN[direction.origin]} · {direction.finding_kind === 'observation' ? '材料观察' : '待核假设'}</p>
                    <h4 className="font-medium">{direction.title}</h4>
                    <p className="whitespace-pre-wrap text-sm leading-7">{direction.description}</p>
                    <Quotes label="支持片段" refs={direction.supporting_refs} onOpenMaterial={onOpenMaterial} />
                    <Quotes label="相反或限制性片段" refs={direction.counter_refs} onOpenMaterial={onOpenMaterial} />
                    {!!direction.missing_information?.length && <p className="text-sm">仍缺信息：{direction.missing_information.join('；')}</p>}
                    {!!direction.alternative_explanations?.length && <p className="text-sm">其他可能解释：{direction.alternative_explanations.join('；')}</p>}
                    {direction.case_context_quote && <p className="text-xs text-slate-500">对应案情表述（非证据）：{direction.case_context_quote}</p>}
                </article>)}
                {!stage.directions.length && <p className="text-sm">本次可读材料未形成有来源支持的调查方向；这不表示不存在相关活动。</p>}
            </div>
        </details>
        {guided && <details open><summary className="cursor-pointer text-sm font-medium">逐项差异 · {stage.comparisons.length} 项</summary>
            <div className="mt-3 space-y-3">{stage.comparisons.map(comparison => <article key={comparison.baseline_direction_id} className="space-y-2 rounded-xl border border-slate-200 p-4 dark:border-slate-600">
                <h4 className="font-medium">{baselineById.get(comparison.baseline_direction_id)?.title || '首次判断'}</h4>
                <p className="text-xs font-semibold text-blue-700 dark:text-blue-300">{STATUS[comparison.status] || '尚待核查'}</p>
                <p className="text-sm leading-7">{comparison.reason}</p>
                <Quotes label="支持片段" refs={comparison.supporting_refs} onOpenMaterial={onOpenMaterial} />
                <Quotes label="相反片段" refs={comparison.counter_refs} onOpenMaterial={onOpenMaterial} />
                {!!comparison.missing_information?.length && <p className="text-sm">仍缺信息：{comparison.missing_information.join('；')}</p>}
            </article>)}</div>
        </details>}
        {guided && <details><summary className="cursor-pointer text-sm">保留首次自主发现 · {stage.baseline_directions.length} 项</summary>
            {stage.baseline_directions.map(d => <p key={d.direction_id} className="mt-3 text-sm leading-7"><strong>{d.title}</strong>：{d.description}</p>)}
        </details>}
        {guided && <details><summary className="cursor-pointer text-sm">核查优先级变化 · {changed.length} 份材料</summary>
            {changed.map(c => <p key={c.evidence_key} className="mt-3 break-all text-xs leading-6">{c.evidence_key}<br />
                首次：{priorityStyle(stage.baseline_priorities[c.evidence_key]).label} → 本轮：{priorityStyle(c.priority).label}<br />依据：{c.reason}</p>)}
        </details>}
        <details><summary className="cursor-pointer text-sm">读取范围与未完成项</summary>
            <ul className="mt-3 space-y-2">{stage.materials.map(m => <li key={m.material_id} className="text-xs leading-6">
                <button type="button" className="text-blue-700 dark:text-blue-300" onClick={() => onOpenMaterial(m.material_id)}>{m.material_id} · {KIND[m.kind] || m.kind}</button>
                {' · '}{m.status === 'unavailable' ? '不可用' : m.status === 'partial' ? '部分可用' : '已冻结'}
                {m.limitations?.length > 0 && ` · ${m.limitations.map(sourceLabel).join('；')}`}
            </li>)}</ul>
            {stage.warnings?.some(w => /REJECTED/.test(w)) && <p className="mt-3 text-xs text-amber-800 dark:text-amber-300">部分模型研判未通过来源校验，对应材料或首次判断仍保留，不能当作已完成验证。</p>}
        </details>
    </section>;
}
