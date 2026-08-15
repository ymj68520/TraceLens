// investigationGraphConstants.js
// Investigation Graph (C8c) 的命名空间颜色与纯函数工具。
// 颜色 key 组合 `${source}:${label}`，保证 Base KG 与 Investigation Overlay
// 即使 label 撞名也不会混色（例如 base_kg:Event vs investigation:InvestigationEvent）。
import { NODE_COLORS } from '../knowledge-graph/graphConstants';

// Investigation Overlay 专用调色板——刻意不与 NODE_COLORS 中的任一色重复。
export const INVESTIGATION_NODE_COLORS = {
    'investigation:InvestigationEvent': '#facc15', // yellow-400
    'investigation:Evidence': '#84cc16',            // lime-500
    'investigation:Analysis': '#3b82f6',            // blue-500
    'investigation:Claim': '#e879f9',               // fuchsia-400
};

// Base KG 节点沿用 KnowledgeGraph 页面的配色，同一 Graphiti 实体在两页观感一致。
export const BASE_NODE_COLOR_FALLBACK = '#94a3b8';

// 页面图例条目（顺序即展示顺序）。
export const NODE_LEGEND = [
    { key: 'investigation:InvestigationEvent', label: 'InvestigationEvent' },
    { key: 'investigation:Evidence', label: 'Evidence' },
    { key: 'investigation:Analysis', label: 'Analysis' },
    { key: 'investigation:Claim', label: 'Claim' },
];

export const colorKeyForNode = (node) => `${node?.source}:${node?.label}`;

export const getNodeColor = (node) => {
    if (!node) return BASE_NODE_COLOR_FALLBACK;
    if (node.source === 'investigation') {
        return INVESTIGATION_NODE_COLORS[colorKeyForNode(node)] || BASE_NODE_COLOR_FALLBACK;
    }
    return NODE_COLORS[node.label] || BASE_NODE_COLOR_FALLBACK;
};

// 只有 Analysis 与 Claim 表达 review 状态；Evidence/Event 永不显示为 unconfirmed。
export const isUnconfirmed = (node) =>
    node?.source === 'investigation' &&
    (node.label === 'Analysis' || node.label === 'Claim') &&
    node.confirmed === false;

export const LINK_COLORS = {
    base_relation: 'rgba(148, 163, 184, 0.6)',
    event_evidence: 'rgba(250, 204, 21, 0.45)',
    analysis_evidence: 'rgba(59, 130, 246, 0.45)',
    analysis_claim: 'rgba(232, 121, 249, 0.45)',
    claim_evidence: 'rgba(132, 204, 22, 0.45)',
};

export const getLinkColor = (link) =>
    LINK_COLORS[link?.kind] || LINK_COLORS.base_relation;

// C8b 的确定性节点 ID：`namespace:value`。value（如 evidence_key）本身可含 ':'，
// 因此只在第一个 ':' 处切分；Base KG 节点保留 Graphiti uuid 原样，无命名空间。
const OVERLAY_NAMESPACES = new Set(['event', 'analysis', 'claim', 'evidence']);

export const parseNodeId = (id) => {
    const text = String(id ?? '');
    const separator = text.indexOf(':');
    if (separator <= 0) {
        return { namespace: 'base_kg', value: text };
    }
    const namespace = text.slice(0, separator);
    const value = text.slice(separator + 1);
    if (!OVERLAY_NAMESPACES.has(namespace)) {
        return { namespace: 'base_kg', value: text };
    }
    return { namespace, value };
};

const escapeHtml = (text) =>
    String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

// react-force-graph 的 nodeLabel 会作为 HTML 注入，必须转义不可信文本。
export const nodeTooltip = (node) => {
    if (!node) return '';
    const lines = [escapeHtml(node.name || node.id)];
    if (node.label) lines.push(`<b>${escapeHtml(node.label)}</b>`);
    if (node.source === 'investigation') {
        const provenance = node.provenance || {};
        if (node.label === 'InvestigationEvent') {
            if (provenance.version !== undefined) {
                lines.push(`v${escapeHtml(provenance.version)}`);
            }
        } else if (node.label === 'Analysis') {
            if (provenance.review_state) lines.push(escapeHtml(provenance.review_state));
            if (provenance.version !== undefined) lines.push(`v${escapeHtml(provenance.version)}`);
            if (provenance.evidence_key) lines.push(escapeHtml(provenance.evidence_key));
        } else if (node.label === 'Claim') {
            if (provenance.claim_type) lines.push(escapeHtml(provenance.claim_type));
            if (provenance.grounding_status) lines.push(escapeHtml(provenance.grounding_status));
        } else if (node.label === 'Evidence') {
            if (provenance.evidence_type) lines.push(escapeHtml(provenance.evidence_type));
        }
        if (isUnconfirmed(node)) lines.push('<b>Unconfirmed</b>');
    } else if (node.summary) {
        lines.push(escapeHtml(node.summary.substring(0, 120)));
    }
    return lines.join('<br/>');
};

export const linkTooltip = (link) => escapeHtml(link?.label || '');
