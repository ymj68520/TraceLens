import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import ReportEvidenceSelector from './ReportEvidenceSelector';

const mockService = (setResponse = { report_evidence: { report_status: 'main' } }) => ({
    setReportEvidence: vi.fn().mockResolvedValue(setResponse),
    removeReportEvidence: vi.fn().mockResolvedValue({}),
});

vi.mock('../../../services/investigationService', () => ({
    setReportEvidence: (...args) => globalThis.__svc.setReportEvidence(...args),
    removeReportEvidence: (...args) => globalThis.__svc.removeReportEvidence(...args),
}));

function renderSelector(evidenceKey, value = null) {
    const onChange = vi.fn();
    render(<ReportEvidenceSelector taskId="t1" evidenceKey={evidenceKey} value={value} onChange={onChange} />);
    return onChange;
}

describe('ReportEvidenceSelector', () => {
    test('cluster evidence offers no add actions and explains the MVP trim', () => {
        globalThis.__svc = mockService();
        renderSelector('cluster:v1:28331457:CREATED');
        const note = screen.getByTestId('report-evidence-cluster-note');
        expect(note).toHaveTextContent(/事件簇证据不作为报告证据/);
        // 绝不渲染会把 cluster 键写进 report_evidence 的按钮
        expect(screen.queryByText('正文证据')).not.toBeInTheDocument();
        expect(screen.queryByText('附件证据')).not.toBeInTheDocument();
    });

    test('file evidence can still be marked as main evidence', async () => {
        globalThis.__svc = mockService();
        renderSelector('file:/case/a.txt');
        fireEvent.click(screen.getByText('正文证据'));
        await waitFor(() => expect(globalThis.__svc.setReportEvidence).toHaveBeenCalledWith(
            't1',
            expect.objectContaining({ evidence_key: 'file:/case/a.txt', usage: 'main' }),
        ));
    });
});
