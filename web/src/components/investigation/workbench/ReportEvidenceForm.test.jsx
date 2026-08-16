import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';

vi.mock('../../../hooks/useTranslation', () => ({
    useTranslation: () => ({ t: (key) => key }),
}));

import ReportEvidenceForm from './ReportEvidenceForm';

const KEY = 'file:/case/a.txt';
const accepted = {
    analysis_id: 'sa_accepted',
    version: 2,
    status: 'accepted',
    evidence_key: KEY,
};
const pending = {
    analysis_id: 'sa_pending',
    version: 3,
    status: 'review_pending',
    evidence_key: KEY,
};

function openForm() {
    return userEvent.click(screen.getByTestId('report-evidence-toggle'));
}

function fillActor() {
    return userEvent.type(screen.getByTestId('report-actor-input'), 'analyst-x');
}

describe('ReportEvidenceForm (R1)', () => {
    test('adds original evidence explicitly without analysis binding', async () => {
        const onAdd = vi.fn().mockResolvedValue({});
        render(<ReportEvidenceForm evidenceKey={KEY} analyses={[accepted, pending]} onAdd={onAdd} onUpdate={vi.fn()} />);

        await openForm();
        expect(screen.getByRole('option', { name: /sa_accepted/ })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: /sa_pending/ })).not.toBeInTheDocument();
        await fillActor();
        await userEvent.click(screen.getByTestId('report-evidence-submit'));

        expect(onAdd).toHaveBeenCalledWith({
            evidenceKey: KEY,
            reportStatus: 'main',
            analysisId: null,
            addedBy: 'analyst-x',
        });
    });

    test('explicitly binds an accepted analysis and never offers review_pending', async () => {
        const onAdd = vi.fn().mockResolvedValue({});
        render(<ReportEvidenceForm evidenceKey={KEY} analyses={[accepted, pending]} onAdd={onAdd} onUpdate={vi.fn()} />);

        await openForm();
        await userEvent.selectOptions(screen.getByTestId('report-analysis-select'), 'sa_accepted');
        await userEvent.selectOptions(screen.getByTestId('report-status-select'), 'appendix');
        await fillActor();
        await userEvent.click(screen.getByTestId('report-evidence-submit'));

        expect(onAdd).toHaveBeenCalledWith({
            evidenceKey: KEY,
            reportStatus: 'appendix',
            analysisId: 'sa_accepted',
            addedBy: 'analyst-x',
        });
    });

    test('renders frozen binding and newer accepted hint', () => {
        render(
            <ReportEvidenceForm
                evidenceKey={KEY}
                analyses={[accepted]}
                reportEvidence={{
                    evidence_key: KEY,
                    report_status: 'main',
                    analysis_id: 'sa_accepted',
                    bound_analysis: { analysis_id: 'sa_accepted', version: 2, decided_by: 'analyst-old' },
                    newer_accepted_available: true,
                }}
                onAdd={vi.fn()}
                onUpdate={vi.fn()}
            />,
        );

        expect(screen.getByTestId('report-binding-summary')).toHaveTextContent('v2');
        expect(screen.getByTestId('report-binding-summary')).toHaveTextContent('sa_accepted');
        expect(screen.getByTestId('newer-accepted-hint')).toBeInTheDocument();
    });

    test('changes status and explicitly rebinds an existing report evidence row', async () => {
        const onUpdate = vi.fn().mockResolvedValue({});
        render(
            <ReportEvidenceForm
                evidenceKey={KEY}
                analyses={[accepted, { ...accepted, analysis_id: 'sa_new', version: 4 }]}
                reportEvidence={{
                    evidence_key: KEY,
                    report_status: 'main',
                    analysis_id: 'sa_accepted',
                    bound_analysis: { analysis_id: 'sa_accepted', version: 2 },
                    newer_accepted_available: true,
                }}
                onAdd={vi.fn()}
                onUpdate={onUpdate}
            />,
        );

        await openForm();
        await userEvent.selectOptions(screen.getByTestId('report-status-select'), 'excluded');
        await userEvent.selectOptions(screen.getByTestId('report-analysis-select'), 'sa_new');
        await fillActor();
        await userEvent.click(screen.getByTestId('report-evidence-submit'));

        expect(onUpdate).toHaveBeenCalledWith({
            evidenceKey: KEY,
            reportStatus: 'excluded',
            analysisId: 'sa_new',
            updatedBy: 'analyst-x',
        });
    });
});
