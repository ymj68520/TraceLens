import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import EvidenceClassification, { ClassificationDetails, ClassificationBadges } from './EvidenceClassification';
import NarrativeReportView from './NarrativeReportView';

const evidence = (key, priority, topics = []) => ({
    evidence_key: key, material_type: 'transaction_record', topics, priority,
    material_states: ['deleted', 'incomplete_provenance'], review_status: 'pending',
    assessment_status: 'classified', reason: '材料涉及付款安排，需要核对金额差异。',
    basis_type: 'initial_analysis', basis_quote: '付款安排', basis_truncated: true,
    relations: [{ question_id: 'q1', relation: 'inconsistent', reason: '核对两处记载口径。' }],
});
const classifications = {
    policy_version: 'evidence-dimensions:v1',
    questions: [{ question_id: 'q1', text: '核查付款安排是否一致' }],
    items: [
        evidence('file:/a.xlsx', 'P1', ['funds', 'communications']),
        { ...evidence('file:/b.txt', 'unassessed'), assessment_status: 'failed', relations: [], material_states: ['insufficient_content'] },
    ],
};
const citations = [
    { citation_id: 'c001', evidence_key: 'file:/a.xlsx' },
    { citation_id: 'c002', evidence_key: 'file:/a.xlsx' },
];
const draw = value => render(<MemoryRouter>{value}</MemoryRouter>);

describe('report evidence dimensions', () => {
    test('shows independent dimensions and the exact basis/question without implying recovery or approval', () => {
        draw(<ClassificationDetails classification={classifications.items[0]} questions={classifications.questions} />);
        expect(screen.getByText('P1 优先核查')).toHaveClass('text-orange-900');
        for (const label of ['交易记录', '资金活动', '通讯联系', '已删除', '来源定位不完整', '分类待复核', '存在不一致']) {
            expect(screen.getByText(label)).toBeInTheDocument();
        }
        expect(screen.getByText(/待核事项（案情背景）/)).toHaveTextContent('核查付款安排是否一致');
        expect(screen.getByText(/分类依据来源/)).toHaveTextContent('初次分析摘要；尚未核对原文');
        expect(screen.queryByText('已恢复')).toBeNull();
        expect(screen.queryByText('分类已确认')).toBeNull();
    });

    test.each([
        ['P1', 'P1 优先核查', 'text-orange-900'],
        ['P2', 'P2 重点关注', 'text-blue-800'],
        ['P3', 'P3 一般参考', 'text-slate-700'],
        ['unassessed', '未评估／依据不足', 'border-dashed'],
        ['invalid', '未评估／依据不足', 'border-dashed'],
    ])('priority %s has a readable label and matching tone', (priority, label, tone) => {
        draw(<ClassificationBadges classification={evidence('file:/a', priority)} />);
        expect(screen.getByText(label)).toHaveClass(tone);
    });

    test.each([['machine_suggested', '机器建议'], ['pending', '分类待复核'],
        ['confirmed', '分类已确认'], ['adjusted', '人工已调整']])('review %s is a separate label', (review_status, label) => {
        draw(<ClassificationBadges classification={{ ...evidence('file:/a', 'P2'), review_status }} />);
        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.getByText('P2 重点关注')).toBeInTheDocument();
    });

    test('counts materials once, retains uncited failures and filters themes/states independently', () => {
        const open = vi.fn();
        draw(<EvidenceClassification classification={classifications} citations={citations} taskId="A" reportId="r" onOpenCitation={open} />);
        expect(screen.getByText('证据分类 · 2 份材料')).toBeInTheDocument();
        expect(screen.getByTestId('priority-count-P1')).toHaveTextContent('· 1');
        expect(screen.getByTestId('priority-count-unassessed')).toHaveTextContent('· 1');
        fireEvent.click(screen.getByText('查看分类材料与依据'));
        expect(screen.getAllByTestId('classified-evidence')).toHaveLength(2);
        fireEvent.change(screen.getByLabelText('筛选业务主题'), { target: { value: 'communications' } });
        expect(screen.getAllByTestId('classified-evidence')).toHaveLength(1);
        fireEvent.click(screen.getByText('查看引用 c001 的证据溯源'));
        expect(open).toHaveBeenCalledWith('c001');
        fireEvent.change(screen.getByLabelText('筛选材料状态'), { target: { value: 'insufficient_content' } });
        expect(screen.getByText('没有符合当前条件的材料。')).toBeInTheDocument();
    });

    test('historical report stays unclassified and deduplicates repeated citations', () => {
        draw(<EvidenceClassification citations={citations} taskId="A" reportId="r" />);
        expect(screen.getByText('证据分类 · 1 份材料')).toBeInTheDocument();
        expect(screen.getByTestId('priority-count-P3')).toHaveTextContent('· 0');
        expect(screen.getByTestId('priority-count-unassessed')).toHaveTextContent('· 1');
    });

    test('narrative citation and drawer use the same frozen annotation; filters never hide prose', async () => {
        const report = { title: '合成报告', version: 1, created_at: 'today', citations,
            evidence_classifications: classifications,
            sections: [{ heading: '资金', content: '核查 a.xlsx 中的付款安排。', citation_ids: ['c001'] }] };
        const fetchNarrative = vi.fn().mockResolvedValue(report);
        draw(<NarrativeReportView taskId="A" reportId="r" fetchNarrative={fetchNarrative}
            fetchSnapshot={vi.fn().mockResolvedValue({})} TracebackPanel={() => <div>原有证据溯源</div>} />);
        const marker = await screen.findByTestId('citation-chip-c001');
        expect(marker).toHaveAttribute('data-priority', 'P1');
        expect(marker).toHaveTextContent('P1 优先核查');
        fireEvent.click(screen.getByText('查看分类材料与依据'));
        fireEvent.change(screen.getByLabelText('筛选核查优先级'), { target: { value: 'unassessed' } });
        expect(screen.getByTestId('narrative-sections')).toHaveTextContent('付款安排');
        fireEvent.click(marker);
        const drawer = screen.getByRole('dialog');
        expect(within(drawer).getByText('原有证据溯源')).toBeInTheDocument();
        expect(within(drawer).getByText('分类待复核')).toBeInTheDocument();
        expect(within(drawer).getByText(/分类依据来源/)).toHaveTextContent('尚未核对原文');
        expect(fetchNarrative).toHaveBeenCalledTimes(1);
    });
});
