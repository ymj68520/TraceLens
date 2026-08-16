import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import NarrativeReportView from './NarrativeReportView';

const NARRATIVE = {
    task_id: 't1',
    report_id: 'rep-1',
    version: 1,
    status: 'ready',
    generation_id: 'rg_1',
    title: 'Narrative Report',
    created_at: '2026-08-16T00:00:00+00:00',
    model: 'm',
    prompt_version: 'final-report:v1',
    input_hash: 'hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh',
    sections: [
        {
            heading: 'Overview',
            content: 'Two items were recovered.',
            citation_ids: ['cit-a'],
        },
        {
            heading: 'Appendix note',
            content: 'Supporting material.',
            citation_ids: [],
        },
    ],
    citations: [
        {
            citation_id: 'cit-a',
            evidence_key: 'file:/case/a.txt',
            analysis_id: null,
            claim_id: null,
            evidence_captured_at: 1000,
            analysis_version: null,
            claim_type: null,
        },
    ],
};

function deferred() {
    let resolve;
    const promise = new Promise((nextResolve) => { resolve = nextResolve; });
    return { promise, resolve };
}

describe('NarrativeReportView', () => {
    test('renders persisted sections, audit metadata, and exact manifest citations', async () => {
        const fetchNarrative = vi.fn().mockResolvedValue(NARRATIVE);
        render(<NarrativeReportView taskId="t1" reportId="rep-1" fetchNarrative={fetchNarrative} />);

        expect(await screen.findByTestId('narrative-sections')).toBeInTheDocument();
        expect(screen.getAllByTestId('narrative-section')).toHaveLength(2);
        expect(screen.getByText('Overview')).toBeInTheDocument();
        expect(screen.getByText('Two items were recovered.')).toBeInTheDocument();
        expect(screen.getByTestId('narrative-audit-metadata')).toHaveTextContent('final-report:v1');
        expect(fetchNarrative).toHaveBeenCalledWith('t1', 'rep-1');
    });

    test('citation click passes the exact manifest entry to the traceback panel', async () => {
        const fetchNarrative = vi.fn().mockResolvedValue(NARRATIVE);
        const TracebackPanel = vi.fn(() => <div data-testid="stub-panel" />);
        render(
            <NarrativeReportView
                taskId="t1"
                reportId="rep-1"
                fetchNarrative={fetchNarrative}
                TracebackPanel={TracebackPanel}
            />,
        );
        fireEvent.click(await screen.findByTestId('citation-chip-cit-a'));
        await waitFor(() => expect(TracebackPanel).toHaveBeenCalled());
        const props = TracebackPanel.mock.calls.at(-1)[0];
        expect(props.citation).toEqual(NARRATIVE.citations[0]);
        expect(props.taskId).toBe('t1');
        expect(props.reportId).toBe('rep-1');
    });

    test('unknown citation id in a corrupted payload fails safely without guessing (§27-9)', async () => {
        const corrupted = {
            ...NARRATIVE,
            sections: [{ heading: 'H', content: 'C', citation_ids: ['cit-ghost'] }],
        };
        render(
            <NarrativeReportView
                taskId="t1"
                reportId="rep-1"
                fetchNarrative={vi.fn().mockResolvedValue(corrupted)}
                TracebackPanel={() => <div data-testid="stub-panel" />}
            />,
        );
        fireEvent.click(await screen.findByTestId('citation-chip-cit-ghost'));
        expect(await screen.findByTestId('citation-unknown-warning')).toHaveTextContent('cit-ghost');
        expect(screen.queryByTestId('stub-panel')).not.toBeInTheDocument();
    });

    test('late response from a previous report identity never overwrites the current view (§23)', async () => {
        const late = deferred();
        const current = deferred();
        const fetchNarrative = vi.fn()
            .mockReturnValueOnce(late.promise)
            .mockReturnValueOnce(current.promise);
        const view = render(
            <NarrativeReportView taskId="t1" reportId="rep-1" fetchNarrative={fetchNarrative} />,
        );
        view.rerender(
            <NarrativeReportView taskId="t1" reportId="rep-2" fetchNarrative={fetchNarrative} />,
        );
        await late.resolve({ ...NARRATIVE, report_id: 'rep-1', title: 'STALE' });
        await current.resolve({ ...NARRATIVE, report_id: 'rep-2', title: 'CURRENT' });

        expect(await screen.findByText('CURRENT')).toBeInTheDocument();
        expect(screen.queryByText('STALE')).not.toBeInTheDocument();
    });

    test('fetch failure renders an integrity-style error, not a crash', async () => {
        render(
            <NarrativeReportView
                taskId="t1"
                reportId="rep-x"
                fetchNarrative={vi.fn().mockRejectedValue({ status: 503, data: { detail: 'report narrative record is unavailable' } })}
            />,
        );
        expect(await screen.findByTestId('narrative-report-error')).toHaveTextContent('503');
    });
});
