import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
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
    test('Android citation previews the frozen row and links to exact result version', async () => {
        const key = `android_artifact:v1:t1:${'a'.repeat(64)}:sms:7`;
        const report = { ...NARRATIVE, prompt_version: 'final-report:v3',
            sections: [{ heading: '短信证据', content: '该短信支持分析。', citation_ids: ['c001'] }],
            citations: [{ citation_id: 'c001', evidence_key: key, analysis_id: 'sa_1',
                claim_id: null, evidence_captured_at: 1000, analysis_version: 1, claim_type: null }] };
        const fetchSnapshot = vi.fn().mockResolvedValue({ evidence_type: 'android_artifact',
            payload: { evidence_type: 'android_artifact', artifact_kind: 'sms', record_id: 7,
                record_fields: { body: '合成短信正文' }, provenance: { input_file: 'candidate_only' } } });
        render(<NarrativeReportView taskId="t1" reportId="rep-1"
            fetchNarrative={vi.fn().mockResolvedValue(report)} fetchSnapshot={fetchSnapshot} />);
        const marker = await screen.findByTestId('citation-chip-c001');
        fireEvent.mouseEnter(marker.parentElement);
        expect(await screen.findByTestId('citation-tooltip-c001')).toHaveTextContent('合成短信正文');
        expect(screen.getByTestId('citation-tooltip-c001')).toHaveTextContent('candidate_only');
        expect(screen.getByTestId('citation-timeline-link-c001')).toHaveAttribute('href',
            `/investigation?task_id=t1&evidence_key=${encodeURIComponent(key)}&report_id=rep-1&citation_id=c001`);
    });
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

    test('unique filename gets an inline superscript with lazy hover summary and scroll target', async () => {
        const report = {
            ...NARRATIVE,
            sections: [{ heading: 'Overview', content: 'Recovered a.txt from the device.', citation_ids: ['cit-a'] }],
        };
        const fetchSnapshot = vi.fn().mockResolvedValue({ payload: {
            name: 'a.txt', initial_summary: 'Short evidence introduction', initial_description: 'Detailed captured description',
        } });
        const TracebackPanel = vi.fn(() => <div data-testid="stub-panel" />);
        render(<NarrativeReportView taskId="t1" reportId="rep-1" fetchNarrative={vi.fn().mockResolvedValue(report)} fetchSnapshot={fetchSnapshot} TracebackPanel={TracebackPanel} />);

        const marker = await screen.findByTestId('citation-chip-cit-a');
        expect(marker.closest('sup') || marker.parentElement).toBeInTheDocument();
        expect(marker.parentElement.parentElement.textContent).toContain('a.txtcit-a');
        fireEvent.mouseEnter(marker.parentElement);
        expect(await screen.findByTestId('citation-tooltip-cit-a')).toHaveTextContent('Short evidence introduction');
        expect(screen.getByTestId('citation-tooltip-cit-a')).toHaveTextContent('Detailed captured description');
        expect(screen.getByTestId('citation-timeline-link-cit-a')).toHaveAttribute('href', '/investigation?task_id=t1&file=%2Fcase%2Fa.txt&report_id=rep-1&citation_id=cit-a');
        expect(fetchSnapshot).toHaveBeenCalledWith('t1', 'file:/case/a.txt');

        fireEvent.click(marker);
        await waitFor(() => expect(TracebackPanel).toHaveBeenCalled());
        expect(screen.getByTestId('citation-evidence-target')).toHaveAttribute('id', 'citation-evidence-cit-a');
        expect(screen.getByRole('dialog', { name: /引用 cit-a 的证据溯源/ })).toBeInTheDocument();
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(screen.queryByTestId('citation-overlay')).not.toBeInTheDocument();
    });

    test('timeline citation deep link highlights the exact report citation', async () => {
        const report = {
            ...NARRATIVE,
            sections: [{ heading: 'Overview', content: 'Recovered a.txt.', citation_ids: ['cit-a'] }],
        };
        render(<NarrativeReportView taskId="t1" reportId="rep-1" focusCitationId="cit-a" fetchNarrative={vi.fn().mockResolvedValue(report)} />);

        const marker = await screen.findByTestId('citation-chip-cit-a');
        expect(marker).toHaveAttribute('id', 'report-citation-cit-a');
        expect(marker.className).toContain('ring-amber-400');
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

    test('sustained 1.5s hover pins the tooltip; outside click or Escape dismisses it', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const report = {
                ...NARRATIVE,
                sections: [{ heading: 'Overview', content: 'Recovered a.txt from the device.', citation_ids: ['cit-a'] }],
            };
            render(<NarrativeReportView taskId="t1" reportId="rep-1" fetchNarrative={vi.fn().mockResolvedValue(report)}
                fetchSnapshot={vi.fn().mockResolvedValue({ payload: { name: 'a.txt', initial_summary: 'Short evidence introduction' } })} />);
            const marker = await screen.findByTestId('citation-chip-cit-a');
            const wrapper = marker.parentElement;

            fireEvent.mouseEnter(wrapper);
            expect(screen.getByTestId('citation-tooltip-cit-a')).toBeInTheDocument();
            fireEvent.mouseLeave(wrapper);
            expect(screen.queryByTestId('citation-tooltip-cit-a')).not.toBeInTheDocument();

            fireEvent.mouseEnter(wrapper);
            act(() => { vi.advanceTimersByTime(1500); });
            fireEvent.mouseLeave(wrapper);
            const tooltip = screen.getByTestId('citation-tooltip-cit-a');
            expect(tooltip).toBeInTheDocument();

            fireEvent.pointerDown(tooltip);
            expect(screen.getByTestId('citation-tooltip-cit-a')).toBeInTheDocument();

            fireEvent.pointerDown(document.body);
            expect(screen.queryByTestId('citation-tooltip-cit-a')).not.toBeInTheDocument();

            fireEvent.mouseEnter(wrapper);
            act(() => { vi.advanceTimersByTime(1500); });
            fireEvent.mouseLeave(wrapper);
            expect(screen.getByTestId('citation-tooltip-cit-a')).toBeInTheDocument();
            fireEvent.keyDown(document.body, { key: 'Escape' });
            expect(screen.queryByTestId('citation-tooltip-cit-a')).not.toBeInTheDocument();
        } finally {
            vi.useRealTimers();
        }
    });

    test('chip click while pinned dismisses the tooltip and opens the traceback drawer', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const report = {
                ...NARRATIVE,
                sections: [{ heading: 'Overview', content: 'Recovered a.txt from the device.', citation_ids: ['cit-a'] }],
            };
            render(<NarrativeReportView taskId="t1" reportId="rep-1" fetchNarrative={vi.fn().mockResolvedValue(report)}
                fetchSnapshot={vi.fn().mockResolvedValue({ payload: { name: 'a.txt', initial_summary: 'Short evidence introduction' } })}
                TracebackPanel={() => <div data-testid="stub-panel" />} />);
            const marker = await screen.findByTestId('citation-chip-cit-a');
            fireEvent.mouseEnter(marker.parentElement);
            act(() => { vi.advanceTimersByTime(1500); });
            expect(screen.getByTestId('citation-tooltip-cit-a')).toBeInTheDocument();

            fireEvent.click(marker);
            expect(screen.getByTestId('citation-overlay')).toBeInTheDocument();
            expect(screen.queryByTestId('citation-tooltip-cit-a')).not.toBeInTheDocument();
        } finally {
            vi.useRealTimers();
        }
    });

    test('chapter summary sits directly under the heading, before the prose', async () => {
        const report = {
            ...NARRATIVE,
            sections: [
                // Chapter 1 keeps its original order (prose … summary);
                // every later chapter leads with the conclusion.
                { heading: '案件总述与证据召回', content: '本轮在已入报的材料范围内研判。',
                  citation_ids: [], summary: '首章的表后总结。' },
                { heading: '话术培训材料', content: '材料包含话术培训文档。',
                  citation_ids: [], summary: '本章材料共同显示存在话术培训文档，仍需原始来源才能定性。' },
            ],
        };
        render(<NarrativeReportView taskId="t1" reportId="rep-1"
            fetchNarrative={vi.fn().mockResolvedValue(report)} />);
        const sections = await screen.findAllByTestId('narrative-section');
        const chapters = sections.filter(s => s.querySelector('h3')?.textContent === '话术培训材料');
        const chapter = chapters[0];
        const summary = chapter.querySelector('[data-testid="chapter-summary"]');
        const body = chapter.querySelector('p.whitespace-pre-wrap');
        const heading = chapter.querySelector('h3');
        expect(summary).toHaveTextContent('本章小结');
        expect(summary).toHaveTextContent('仍需原始来源才能定性');
        // Summary before body, and after the heading.
        expect(summary.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(heading.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    test('older reports without a summary render unchanged', async () => {
        render(<NarrativeReportView taskId="t1" reportId="rep-1"
            fetchNarrative={vi.fn().mockResolvedValue(NARRATIVE)} />);
        await screen.findByTestId('narrative-sections');
        expect(screen.queryByTestId('chapter-summary')).not.toBeInTheDocument();
        expect(screen.queryByTestId('evidence-recall-table')).not.toBeInTheDocument();
    });

    test('first chapter renders the recall table between prose and summary', async () => {
        const report = {
            ...NARRATIVE,
            sections: [{
                heading: '案件总述与证据召回',
                content: '本轮在已入报的 2 份材料范围内研判。\n\n全案总述：材料显示存在付款安排。',
                citation_ids: [],
                summary: '2 份入报材料中有 1 份被正文实际引用，其余未构成结论依据。',
                recall_table: {
                    title: '证据召回表',
                    total_materials: 2,
                    recalled_materials: 1,
                    unavailable_materials: 0,
                    total_citations: 3,
                    rows: [{
                        citation_id: 'c001',
                        evidence_key: 'file:/case/往来记录.txt',
                        evidence_name: '往来记录.txt',
                        material_type: 'document',
                        priority: 'P1',
                        topics: ['funds'],
                        reference_count: 3,
                        chapter_count: 2,
                        material_status: 'ready',
                        contribution: '支撑付款安排的认定，正文引用该记录中的转账摘录；'
                            + '仍未与具体账户建立归属关系，因此只作为待核线索。',
                    }],
                    notes: ['另有 1 份可用材料未被任何章节引用，其内容未进入本报告正文。'],
                },
            }],
            citations: [{ citation_id: 'c001', evidence_key: 'file:/case/往来记录.txt',
                analysis_id: null, claim_id: null }],
        };
        const TracebackPanel = vi.fn(() => <div data-testid="stub-panel" />);
        render(<NarrativeReportView taskId="t1" reportId="rep-1"
            fetchNarrative={vi.fn().mockResolvedValue(report)} TracebackPanel={TracebackPanel} />);

        const table = await screen.findByTestId('evidence-recall-table');
        expect(table).toHaveTextContent('证据召回表');
        expect(table).toHaveTextContent('入报 2 份');
        expect(table).toHaveTextContent('往来记录.txt');
        expect(table).toHaveTextContent('资金活动');
        expect(screen.getByTestId('recall-row')).toBeInTheDocument();
        expect(table).toHaveTextContent('未被任何章节引用');
        // The three former columns (priority / citation count / chapter count)
        // became one explanation of what the material contributed to the case.
        expect(table).not.toHaveTextContent('核查优先级');
        expect(table).not.toHaveTextContent('引用次数');
        expect(table).not.toHaveTextContent('涉及章节');
        expect(table).toHaveTextContent('对本案的作用');
        expect(screen.getByTestId('recall-contribution'))
            .toHaveTextContent('支撑付款安排的认定');
        // Counts survive only as a footnote.
        expect(table).toHaveTextContent('被引 3 处 · 涉及 2 章');
        const section = table.closest('[data-testid="narrative-section"]');
        // The chapter badge must describe the table's coverage, not claim zero
        // citations just because the chapter itself carries no citation_ids.
        expect(section.textContent).toContain('1 份被引材料');
        const summary = screen.getByTestId('chapter-summary');
        expect(section.contains(summary)).toBe(true);
        expect(table.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

        fireEvent.click(screen.getByTestId('recall-citation-c001'));
        await waitFor(() => expect(TracebackPanel).toHaveBeenCalled());
        expect(TracebackPanel.mock.calls[0][0].citation.citation_id).toBe('c001');
    });
});
