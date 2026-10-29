import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import CommTimelinePanel from './CommTimelinePanel';

vi.mock('../../services/commGraphService', () => ({
    getCommTimeline: vi.fn(),
}));

vi.mock('react-virtuoso', () => ({
    // jsdom has no layout; render every row so assertions can see them.
    Virtuoso: ({ data, itemContent }) => (
        <div data-testid="comm-timeline-list">
            {data.map((record, index) => <div key={record.record_ref}>{itemContent(index, record)}</div>)}
        </div>
    ),
}));

import { getCommTimeline } from '../../services/commGraphService';

const payload = {
    success: true,
    task_id: 'T1',
    records: [
        { timestamp: 1772359200, kind: 'call', kind_label: '通话', dataset: 'task:T1', actor: '本机', actor_id: 'p_o', peer: '张三', peer_id: 'p_z', group: '', direction: 'received', summary: '通话 65 秒', record_ref: 'task:T1|call_logs|1' },
        { timestamp: 1772445600, kind: 'sms', kind_label: '短信', dataset: 'task:T1', actor: '本机', actor_id: 'p_o', peer: '李四', peer_id: 'p_l', group: '', direction: 'sent', summary: '晚点到', record_ref: 'task:T1|sms_messages|1' },
    ],
    sources: [{ dataset_id: 'task:T1', status: 'read', records_scanned: 2 }],
    coverage: {
        datasets_scanned: 1, records_scanned: 2, filtered_kind: 0, filtered_time: 0,
        duplicates: 0, records_total: 2, records_returned: 2, records_truncated: 0,
        dedup_rule: 'dataset+record_ref:v1', truncated_sources: [],
    },
};

describe('CommTimelinePanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getCommTimeline.mockResolvedValue(payload);
    });

    it('renders records in the order the API returns and shows coverage', async () => {
        render(<CommTimelinePanel taskId="T1" />);
        expect(await screen.findByText(/通话 65 秒/)).toBeInTheDocument();
        expect(screen.getByText(/返回 2 \/ 命中 2/)).toBeInTheDocument();
        expect(screen.getByText(/去重口径 dataset\+record_ref:v1/)).toBeInTheDocument();
        expect(screen.getByText(/同一句话出现在两个数据集时保留为两条记录/)).toBeInTheDocument();
    });

    it('sends repeated kind filters when a type is toggled', async () => {
        render(<CommTimelinePanel taskId="T1" />);
        await waitFor(() => expect(getCommTimeline).toHaveBeenCalled());
        await userEvent.click(screen.getByRole('button', { name: '短信' }));
        await waitFor(() => {
            const last = getCommTimeline.mock.calls.at(-1)[1];
            expect(last.kinds).toEqual(['sms']);
        });
    });

    it('converts the local time inputs to epoch seconds', async () => {
        render(<CommTimelinePanel taskId="T1" />);
        await waitFor(() => expect(getCommTimeline).toHaveBeenCalled());
        await userEvent.type(screen.getByLabelText('时间线开始时间'), '2026-03-01T08:30');
        await waitFor(() => {
            const last = getCommTimeline.mock.calls.at(-1)[1];
            expect(Number.isInteger(last.startTime)).toBe(true);
            expect(last.startTime).toBeGreaterThan(1_700_000_000);
        });
    });

    it('states that no records does not mean no contact', async () => {
        getCommTimeline.mockResolvedValue({
            ...payload, records: [],
            coverage: { ...payload.coverage, records_total: 0, records_returned: 0 },
        });
        render(<CommTimelinePanel taskId="T1" />);
        expect(await screen.findByText(/没有记录不等于没有联系/)).toBeInTheDocument();
    });

    it('surfaces an unreadable dataset instead of an empty list', async () => {
        getCommTimeline.mockResolvedValue({
            ...payload,
            sources: [{ dataset_id: 'task:T1', status: 'unreadable' }],
        });
        render(<CommTimelinePanel taskId="T1" />);
        expect(await screen.findByText(/有数据集不可读取/)).toBeInTheDocument();
    });
});
