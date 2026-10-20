import { useMemo, useState } from 'react';
import { FileText, Image as ImageIcon, MessagesSquare, Receipt, ScrollText, Smartphone, HelpCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { investigationEvidenceUrl } from '../../utils/evidenceKey';
import { PRIORITIES, TOPICS, priorityStyle } from './evidenceClassificationStyles';
const MATERIALS = {
    document: ['文档', FileText], chat_record: ['聊天记录', MessagesSquare],
    transaction_record: ['交易记录', Receipt], image: ['图片', ImageIcon],
    log: ['日志', ScrollText], android_artifact: ['Android工件', Smartphone],
    other: ['其他材料', FileText], unknown: ['类型未确定', HelpCircle],
};
const STATES = { deleted: '已删除', recovered: '已恢复', insufficient_content: '内容不足', incomplete_provenance: '来源定位不完整' };
const REVIEWS = { machine_suggested: '机器建议', pending: '分类待复核', confirmed: '分类已确认', adjusted: '人工已调整' };
const RELATIONS = { supports: '支持线索', inconsistent: '存在不一致', background: '背景材料', unknown: '暂无法判断' };
const BASIS = { initial_analysis: '初次分析摘要；尚未核对原文', android_record: '冻结的 Android 派生解析记录；不代表已核对原库', metadata: '文件元数据；缺少可用内容' };
const chip = 'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs leading-5';
const neutral = 'border-slate-200 bg-white text-slate-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300';

export function ClassificationBadges({ classification, compact = false }) {
    const value = classification || {};
    const priority = priorityStyle(value.priority);
    const [typeLabel, Icon] = MATERIALS[value.material_type] || MATERIALS.unknown;
    return <span className="inline-flex flex-wrap items-center gap-1.5" aria-label="证据分类标记">
        <span data-priority={PRIORITIES[value.priority] ? value.priority : 'unassessed'} className={`${chip} font-semibold ${priority.tone}`}>{priority.label}</span>
        {!compact && <span className={`${chip} ${neutral}`}><Icon size={13} aria-hidden />{typeLabel}</span>}
        {(value.topics || []).map(topic => <span key={topic} className={`${chip} ${neutral}`}>{TOPICS[topic] || '主题未确定'}</span>)}
        {!compact && (value.material_states || []).map(state => <span key={state} className={`${chip} ${neutral}`}>{STATES[state] || '状态未确定'}</span>)}
        {!compact && <span className={`${chip} ${neutral}`}>{classification ? (REVIEWS[value.review_status] || '复核状态未知') : '历史未分类'}</span>}
    </span>;
}

export function ClassificationDetails({ classification, questions = [] }) {
    if (!classification) return <p className="text-xs text-slate-500">历史报告没有冻结的分类信息，未自动推定优先级。</p>;
    const byId = new Map(questions.map(q => [q.question_id, q.text]));
    return <div className="space-y-3 text-sm leading-6 text-slate-700 dark:text-slate-200" data-testid="classification-details">
        <ClassificationBadges classification={classification} />
        <p className="text-slate-700 dark:text-slate-200">依据：{classification.reason}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">分类依据来源：{BASIS[classification.basis_type] || '来源类型未知'}{classification.basis_truncated ? '；仅使用部分摘要或记录内容' : ''}</p>
        {classification.basis_quote && <blockquote className="whitespace-pre-wrap break-words border-l-2 border-slate-300 pl-3 text-xs text-slate-600 dark:text-slate-300">依据摘录（上述来源）：{classification.basis_quote}</blockquote>}
        {classification.relations?.length ? <ul className="space-y-2">
            {classification.relations.map(relation => <li key={relation.question_id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400">待核事项（案情背景）：{byId.get(relation.question_id) || '对应事项不可用'}</p>
                <p className="mt-1"><span className="font-medium">{RELATIONS[relation.relation] || RELATIONS.unknown}</span> · {relation.reason}</p>
            </li>)}
        </ul> : <p className="text-xs text-slate-500 dark:text-slate-400">与待核问题的关系：暂无法判断。</p>}
        <p className="text-xs text-slate-500 dark:text-slate-400">机器分类用于阅读与核查，不表示事实已证实，也不改变正文／附录的入报选择。</p>
    </div>;
}

export default function EvidenceClassification({ classification, citations = [], taskId, reportId, onOpenCitation }) {
    const [priority, setPriority] = useState('all');
    const [topic, setTopic] = useState('all');
    const [materialState, setMaterialState] = useState('all');
    const items = useMemo(() => {
        if (classification) return classification.items || [];
        return [...new Set(citations.map(c => c.evidence_key))].map(evidence_key => ({ evidence_key, priority: 'unassessed' }));
    }, [classification, citations]);
    const counts = items.reduce((result, item) => {
        const key = PRIORITIES[item.priority] ? item.priority : 'unassessed';
        result[key] += 1;
        return result;
    }, { P1: 0, P2: 0, P3: 0, unassessed: 0 });
    const visible = items.filter(item => (priority === 'all' || (PRIORITIES[item.priority] ? item.priority : 'unassessed') === priority)
        && (topic === 'all' || item.topics?.includes(topic))
        && (materialState === 'all' || item.material_states?.includes(materialState)))
        .sort((a, b) => priorityStyle(a.priority).order - priorityStyle(b.priority).order || a.evidence_key.localeCompare(b.evidence_key));
    return <section className="rounded-2xl border border-slate-200 bg-white p-5 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200" aria-label="报告证据分类" data-testid="report-classifications">
        <h3 className="font-semibold text-slate-900 dark:text-white">证据分类 · {items.length} 份材料</h3>
        <p className="mt-2 text-xs leading-6 text-slate-500 dark:text-slate-400">颜色表示核查顺序；同一材料可有多个主题。下方筛选仅影响材料清单，报告正文完整保留。</p>
        {!classification && <p className="mt-2 text-xs text-slate-500">历史报告未分类，当前仅列出其冻结引用材料。</p>}
        <div className="mt-3 flex flex-wrap gap-2" aria-label="核查优先级图例">
            {Object.entries(PRIORITIES).map(([key, value]) => <span key={key} data-testid={`priority-count-${key}`} className={`${chip} ${value.tone}`}>{value.label} · {counts[key]}</span>)}
        </div>
        <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-200">查看分类材料与依据</summary>
            <div className="my-4 flex flex-wrap gap-3 text-sm">
                <label>核查优先级 <select aria-label="筛选核查优先级" value={priority} onChange={e => setPriority(e.target.value)} className={`rounded-md ${neutral}`}><option value="all">全部</option>{Object.entries(PRIORITIES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
                <label>业务主题 <select aria-label="筛选业务主题" value={topic} onChange={e => setTopic(e.target.value)} className={`rounded-md ${neutral}`}><option value="all">全部</option>{Object.entries(TOPICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                <label>材料状态 <select aria-label="筛选材料状态" value={materialState} onChange={e => setMaterialState(e.target.value)} className={`rounded-md ${neutral}`}><option value="all">全部</option>{Object.entries(STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            </div>
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">显示 {visible.length} / {items.length} 份材料，按核查优先级排列。</p>
            <div className="max-h-[40rem] space-y-3 overflow-y-auto">
                {visible.map(item => {
                    const citation = citations.find(c => c.evidence_key === item.evidence_key);
                    const href = investigationEvidenceUrl(taskId, item.evidence_key, { reportId, citationId: citation?.citation_id });
                    return <div key={item.evidence_key} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700" data-testid="classified-evidence">
                        <p className="mb-3 break-all text-xs font-medium text-slate-700 dark:text-slate-200">{item.evidence_key}</p>
                        <ClassificationDetails classification={classification ? item : null} questions={classification?.questions} />
                        {citation ? <button type="button" className="mt-3 text-xs font-medium text-blue-700 dark:text-blue-300" onClick={() => onOpenCitation(citation.citation_id)}>查看引用 {citation.citation_id} 的证据溯源</button>
                            : href && <Link className="mt-3 inline-block text-xs text-blue-700 dark:text-blue-300" to={href}>查看材料（正文未引用）</Link>}
                    </div>;
                })}
                {!visible.length && <p className="py-4 text-sm text-slate-500">没有符合当前条件的材料。</p>}
            </div>
        </details>
    </section>;
}
