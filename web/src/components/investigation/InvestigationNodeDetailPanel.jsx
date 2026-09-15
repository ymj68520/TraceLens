// InvestigationNodeDetailPanel.jsx
// Investigation Graph 节点详情面板（自原 /investigation-graph 独立页抽取）。
// §15：按 node 类型展示后端已冻结的 provenance 字段；本组件不发起任何请求。
import { MousePointerClick } from 'lucide-react';
import Badge from '../common/Badge';
import { getNodeColor, isUnconfirmed, parseNodeId } from './investigationGraphConstants';
import { useTranslation } from '../../hooks/useTranslation';

const ProvenanceRow = ({ label, value }) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
        <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
            {value === undefined || value === null || value === '' ? '-' : String(value)}
        </span>
    </div>
);

const provenanceRows = (node) => {
    const provenance = node.provenance || {};
    if (node.source !== 'investigation') {
        return [
            { label: 'name', value: node.name },
            { label: 'label', value: node.label },
        ];
    }
    switch (node.label) {
        case 'InvestigationEvent':
            return [
                { label: 'title', value: node.name },
                { label: 'current version', value: provenance.version },
            ];
        case 'Analysis':
            return [
                { label: 'review_state', value: provenance.review_state },
                { label: 'confirmed', value: node.confirmed === null ? '-' : String(node.confirmed) },
                { label: 'version', value: provenance.version },
                { label: 'evidence_key', value: provenance.evidence_key },
            ];
        case 'Claim':
            return [
                { label: 'claim_type', value: provenance.claim_type },
                { label: 'grounding_status', value: provenance.grounding_status },
                { label: 'confirmed', value: node.confirmed === null ? '-' : String(node.confirmed) },
                { label: 'analysis_id', value: provenance.analysis_id },
            ];
        case 'Evidence':
            return [
                { label: 'evidence_key', value: provenance.evidence_key ?? node.name },
                { label: 'evidence_type', value: provenance.evidence_type },
            ];
        default:
            return [];
    }
};

const InvestigationNodeDetailPanel = ({ node }) => {
    const { t } = useTranslation();
    if (!node) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-400 dark:text-slate-500 py-16">
                <MousePointerClick size={22} />
                <p className="text-xs">{t('investigation_graph.select_hint')}</p>
            </div>
        );
    }

    const { namespace, value } = parseNodeId(node.id);

    return (
        <div className="space-y-3 overflow-y-auto h-full">
            <div className="flex items-center gap-2 flex-wrap">
                <span
                    className="inline-block h-3 w-3 rounded-full shrink-0"
                    style={{ backgroundColor: getNodeColor(node) }}
                    aria-label={`color ${node.source}:${node.label}`}
                />
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 break-all">
                    {node.name || node.id}
                </span>
                {node.confirmed === true && (
                    <Badge variant="green" size="sm">{t('investigation_graph.confirmed')}</Badge>
                )}
                {isUnconfirmed(node) && (
                    <Badge variant="yellow" size="sm">{t('investigation_graph.unconfirmed')}</Badge>
                )}
            </div>

            <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2">
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">id</span>
                    <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
                        {node.id}
                    </span>
                </div>
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">namespace</span>
                    <span className="text-xs font-mono text-slate-700 dark:text-slate-200">{namespace}</span>
                </div>
                {namespace !== 'base_kg' && (
                    <div className="flex items-baseline justify-between gap-3 py-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">{namespace}_id</span>
                        <span className="text-xs font-mono text-right break-all text-slate-700 dark:text-slate-200">
                            {value}
                        </span>
                    </div>
                )}
                <div className="flex items-baseline justify-between gap-3 py-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">source</span>
                    <span className="text-xs font-mono text-slate-700 dark:text-slate-200">{node.source}</span>
                </div>
            </div>

            {node.summary && (
                <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words">
                    {node.summary}
                </p>
            )}

            <div className="rounded-xl bg-slate-50/80 dark:bg-slate-800/50 px-3 py-2">
                {provenanceRows(node).map((row) => (
                    <ProvenanceRow key={row.label} label={row.label} value={row.value} />
                ))}
            </div>
        </div>
    );
};

export default InvestigationNodeDetailPanel;
