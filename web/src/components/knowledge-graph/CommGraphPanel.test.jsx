import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import CommGraphPanel from './CommGraphPanel';

vi.mock('../../services/commGraphService', () => ({
    getCommGraph: vi.fn(),
    getCommEdgeDetail: vi.fn(),
}));

vi.mock('../../services/wechatForensicsService', () => ({
    listWeChatImports: vi.fn(async () => ({ imports: [
        { import_id: 'wxface01', name: '微信-案例A', status: 'ready' },
    ] })),
}));

vi.mock('../../services/qqForensicsService', () => ({
    listQQImports: vi.fn(async () => ({ imports: [
        { import_id: 'qqface01', name: '老QQ-案例A', status: 'ready' },
    ] })),
}));

// force-graph needs a real canvas; jsdom has none. The canvas is not what these
// tests assert — the panel's data wiring and coverage disclosure are.
vi.mock('react-force-graph-2d', () => ({
    default: ({ graphData, onLinkClick }) => (
        <div data-testid="comm-canvas">
            {graphData.nodes.map((node) => <span key={node.id}>{node.label}</span>)}
            {graphData.links.map((link) => (
                <button key={link.id} type="button"
                    onClick={() => onLinkClick?.(link)}>
                    edge-{link.relation}
                </button>
            ))}
        </div>
    ),
}));

import { getCommEdgeDetail, getCommGraph } from '../../services/commGraphService';

const graphPayload = {
    success: true,
    task_id: 'T1',
    nodes: [
        { id: 'p_owner', label: '本人', kind: 'owner', is_owner: true, identities: { wxid: ['wxid_owner'] }, datasets: ['task:T1'], message_count: 2, call_count: 1, sms_count: 1, first_time: 1772359200, last_time: 1772704800, display_variants: [], identity_conflicts: [] },
        { id: 'p_zhang', label: '张三', kind: 'person', is_owner: false, identities: { phone: ['13800138000'], wxid: ['wxid_zhangsan'] }, datasets: ['task:T1'], message_count: 2, call_count: 1, sms_count: 1, first_time: 1772359200, last_time: 1772704800, display_variants: ['张三'], identity_conflicts: [] },
    ],
    edges: [
        { id: 'e1', source: 'p_owner', target: 'p_zhang', relation: 'call', dataset: 'task:T1', direction: 'received', weight: 3, duration_seconds: 65, first_time: 1772359200, last_time: 1772532000, media_count: 0, sample: '', record_refs: ['task:T1|call_logs|1'], truncated_refs: 0 },
    ],
    communities: [['p_owner', 'p_zhang']],
    coverage: {
        datasets_total: 1, datasets_readable: 1, datasets_unavailable: 0,
        messages_read: 2, calls_read: 1, sms_read: 1, contacts_read: 2, artifacts_read: 0,
        truncated_sources: 0, merged_identities: 1, name_candidates: 0, orphan_records: 0,
        owner_unknown_datasets: 0, nodes_total: 2, nodes_shown: 2, nodes_truncated: 0,
        edges_total: 1, edges_shown: 1, edges_truncated: 0,
        identity_policy: 'strong_keys_only',
    },
    metrics: {},
    datasets: [{ dataset_id: 'task:T1', kind: 'task', id: 'T1', label: '手机检材 case', tables: [] }],
    candidates: [],
    filters: {},
};

describe('CommGraphPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getCommGraph.mockResolvedValue(graphPayload);
    });

    it('shows the merged coverage and dataset label', async () => {
        render(<CommGraphPanel taskId="T1" />);
        await waitFor(() => expect(getCommGraph).toHaveBeenCalled());
        expect(await screen.findByText('数据集：可读 1 / 共 1')).toBeInTheDocument();
        expect(screen.getByText('手机检材 case')).toBeInTheDocument();
        expect(screen.getByText(/仅按号码 \/ wxid \/ QQ 号一致合并人物/)).toBeInTheDocument();
    });

    it('reports same-name candidates without merging them', async () => {
        getCommGraph.mockResolvedValue({
            ...graphPayload,
            candidates: [{ left: 'p_a', right: 'p_b', name: '王五', reason: 'same_display_name_different_identities', auto_merged: false }],
        });
        render(<CommGraphPanel taskId="T1" />);
        expect(await screen.findByText('同名待确认（1）')).toBeInTheDocument();
        expect(screen.getByText(/王五：两个不同身份，未自动合并/)).toBeInTheDocument();
    });

    it('says "no records" without claiming there was no contact', async () => {
        getCommGraph.mockResolvedValue({
            ...graphPayload,
            nodes: [], edges: [],
            coverage: { ...graphPayload.coverage, nodes_total: 0, nodes_shown: 0, edges_total: 0, edges_shown: 0 },
        });
        render(<CommGraphPanel taskId="T1" />);
        expect(await screen.findByText(/没有记录不等于没有联系/)).toBeInTheDocument();
    });

    it('passes the time range to the API and refreshes', async () => {
        render(<CommGraphPanel taskId="T1" />);
        await waitFor(() => expect(getCommGraph).toHaveBeenCalled());
        await userEvent.type(screen.getByLabelText('开始时间'), '2026-03-01T00:00');
        await waitFor(() => {
            const last = getCommGraph.mock.calls.at(-1)[1];
            expect(last.startTime).toBeTruthy();
        });
    });

    it('drills into an edge and lists the underlying records', async () => {
        getCommEdgeDetail.mockResolvedValue({
            records: [{ timestamp: 1772359200, kind: 'call', kind_label: '通话', dataset: 'task:T1', actor: '张三', peer: '本人', direction: 'received', summary: '通话 65 秒', record_ref: 'task:T1|call_logs|1' }],
            total: 1, truncated: 0, source: 'p_owner', target: 'p_zhang', relation: 'call', ref: 'edge:x',
        });
        render(<CommGraphPanel taskId="T1" wechatImports={[]} qqImports={[]} />);
        await waitFor(() => expect(getCommGraph).toHaveBeenCalled());

        await userEvent.click(await screen.findByRole('button', { name: 'edge-call' }));

        await waitFor(() => expect(getCommEdgeDetail).toHaveBeenCalledWith(
            'T1',
            { source: 'p_owner', target: 'p_zhang', relation: 'call' },
            expect.objectContaining({ wechatImports: [] }),
        ));
        expect(await screen.findByText(/通话 65 秒/)).toBeInTheDocument();
        expect(screen.getByText('task:T1|call_logs|1')).toBeInTheDocument();
    });

    it('forwards explicit imports so a case can merge several datasets', async () => {
        render(<CommGraphPanel taskId="T1" wechatImports={['abcdef123456']} qqImports={['123456abcdef']} />);
        await waitFor(() => expect(getCommGraph).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({
                wechatImports: ['abcdef123456'],
                qqImports: ['123456abcdef'],
            }),
        ));
    });

    it('auto-merges ready imports into the graph by default', async () => {
        render(<CommGraphPanel taskId="T1" />);
        await waitFor(() => expect(getCommGraph).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({
                wechatImports: ['wxface01'],
                qqImports: ['qqface01'],
            }),
        ));
        // 数据集可以被摘除
        await userEvent.click(screen.getByLabelText('微信 微信-案例A'));
        await waitFor(() => expect(getCommGraph).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({
                wechatImports: [],
                qqImports: ['qqface01'],
            }),
        ));
    });
});
