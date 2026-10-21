import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import GenerateReportPanel from './GenerateReportPanel';
import NarrativeReportView from './NarrativeReportView';

const source = { material_id: 'm0001', evidence_key: 'file:/records/a.txt', kind: 'text',
    text: '本轮冻结原文：记录需要核查。', source_sha256: 'a'.repeat(64), content_sha256: 'b'.repeat(64),
    original_characters: 16, status: 'ready', limitations: [] };
const direction = { direction_id: 'd1', title: '首次材料线索', description: '核查材料记载。',
    finding_kind: 'hypothesis', supporting_refs: [{ material_id: 'm0001', quote: '记录需要核查', character_start: 7, character_end: 13 }],
    counter_refs: [], missing_information: ['原始业务凭据'], alternative_explanations: ['正常业务解释'], origin: 'material' };
const stageA = { analysis_mode: 'evidence_only', evidence_scope_hash: 'scope', materials: [source],
    directions: [direction], comparisons: [], baseline_directions: [], baseline_priorities: {}, warnings: [] };
const stageB = { ...stageA, analysis_mode: 'case_guided', case_description: '本次待核案情',
    baseline_report_id: 'report-a', baseline_directions: [direction],
    comparisons: [{ baseline_direction_id: 'd1', status: 'insufficient', reason: '材料不足，保留首次线索。',
        supporting_refs: [], counter_refs: [], missing_information: ['原始凭据'] }] };
const report = stage => ({ task_id: 'T', report_id: 'report-a', title: '合成报告', version: 1,
    created_at: 'today', stage_analysis: stage,
    citations: [{ citation_id: 'c001', evidence_key: source.evidence_key }],
    sections: [{ heading: '观察', content: 'a.txt 记录需核查。', citation_ids: ['c001'] }] });
const draw = component => render(<MemoryRouter>{component}</MemoryRouter>);
const loader = vi.fn().mockResolvedValue([]);
const taskLoader = vi.fn().mockResolvedValue({ case_description: '已保存的案情' });

describe('two-stage report UI', () => {
    test('first stage never sends the saved case text', async () => {
        const generate = vi.fn().mockResolvedValue({ generation_id: 'g' });
        draw(<GenerateReportPanel taskId="T" generate={generate} evidenceLoader={loader}
            taskLoader={taskLoader} fetchGeneration={vi.fn()} />);
        fireEvent.change(screen.getByTestId('generate-actor-input'), { target: { value: 'analyst' } });
        fireEvent.click(screen.getByLabelText('首次：材料自主研判'));
        fireEvent.click(screen.getByTestId('generate-submit'));
        await waitFor(() => expect(generate).toHaveBeenCalledWith('T', { requestedBy: 'analyst', analysisMode: 'evidence_only' }));
        expect(screen.queryByLabelText('本次案情描述')).toBeNull();
    });

    test('second stage submits exact baseline and edited context, without saving the task', async () => {
        const generate = vi.fn().mockResolvedValue({ generation_id: 'g' });
        draw(<GenerateReportPanel taskId="T" selectedReportId="report-a" generate={generate}
            evidenceLoader={loader} taskLoader={taskLoader} narrativeLoader={vi.fn().mockResolvedValue(report(stageA))}
            fetchGeneration={vi.fn()} />);
        fireEvent.click(screen.getByLabelText('二次：案情对照研判'));
        await screen.findByText(/基于首次报告 report-a/);
        expect(screen.getByLabelText('本次案情描述')).toHaveValue('已保存的案情');
        fireEvent.change(screen.getByLabelText('本次案情描述'), { target: { value: '本次修订案情' } });
        fireEvent.change(screen.getByTestId('generate-actor-input'), { target: { value: 'analyst' } });
        fireEvent.click(screen.getByTestId('generate-submit'));
        await waitFor(() => expect(generate).toHaveBeenCalledWith('T', {
            requestedBy: 'analyst', analysisMode: 'case_guided', baseReportId: 'report-a', caseDescription: '本次修订案情',
        }));
    });

    test('legacy reports cannot enable a neutral baseline', async () => {
        draw(<GenerateReportPanel taskId="T" selectedReportId="legacy" evidenceLoader={loader}
            taskLoader={taskLoader} narrativeLoader={vi.fn().mockResolvedValue({ title: 'legacy' })} />);
        fireEvent.click(screen.getByLabelText('二次：案情对照研判'));
        await screen.findByText(/历史案情报告不能作为中立基线/);
        fireEvent.change(screen.getByTestId('generate-actor-input'), { target: { value: 'analyst' } });
        expect(screen.getByTestId('generate-submit')).toBeDisabled();
    });

    test('late baseline response from another task cannot enable a second stage', async () => {
        let resolve;
        const narrativeLoader = vi.fn().mockReturnValue(new Promise(done => { resolve = done; }));
        const view = draw(<GenerateReportPanel taskId="T" selectedReportId="report-a" evidenceLoader={loader}
            taskLoader={taskLoader} narrativeLoader={narrativeLoader} />);
        view.rerender(<MemoryRouter><GenerateReportPanel taskId="U" selectedReportId={null} evidenceLoader={loader}
            taskLoader={taskLoader} narrativeLoader={narrativeLoader} /></MemoryRouter>);
        await act(async () => resolve(report(stageA)));
        fireEvent.click(screen.getByLabelText('二次：案情对照研判'));
        expect(screen.getByTestId('generate-submit')).toBeDisabled();
        expect(screen.queryByText(/基于首次报告 report-a/)).toBeNull();
    });

    test('an edited context is not overwritten by a late task lookup', async () => {
        let resolve;
        draw(<GenerateReportPanel taskId="T" evidenceLoader={loader}
            taskLoader={vi.fn().mockReturnValue(new Promise(done => { resolve = done; }))} />);
        fireEvent.click(screen.getByLabelText('二次：案情对照研判'));
        fireEvent.change(screen.getByLabelText('本次案情描述'), { target: { value: '用户正在编辑' } });
        await act(async () => resolve({ case_description: '迟到的旧案情' }));
        expect(screen.getByLabelText('本次案情描述')).toHaveValue('用户正在编辑');
    });

    test('source preview and drawer use frozen raw material instead of the historical AI summary', async () => {
        const fetchSnapshot = vi.fn().mockResolvedValue({ payload: { initial_summary: '不得混入的旧案情摘要' } });
        draw(<NarrativeReportView taskId="T" reportId="report-a" fetchSnapshot={fetchSnapshot}
            fetchNarrative={vi.fn().mockResolvedValue(report(stageA))} />);
        const marker = await screen.findByTestId('citation-chip-c001');
        fireEvent.mouseEnter(marker.parentElement);
        expect(await screen.findByTestId('citation-tooltip-c001')).toHaveTextContent(source.text);
        fireEvent.click(marker);
        const dialog = screen.getByRole('dialog');
        expect(within(dialog).getByText(source.text)).toBeInTheDocument();
        expect(fetchSnapshot).not.toHaveBeenCalled();
        expect(screen.queryByText('不得混入的旧案情摘要')).toBeNull();
    });

    test('case-guided report preserves baseline directions and provides exact backlink', async () => {
        draw(<NarrativeReportView taskId="T" reportId="report-b" fetchNarrative={vi.fn().mockResolvedValue(report(stageB))} />);
        await screen.findByTestId('stage-analysis');
        expect(screen.getByTestId('baseline-report-link')).toHaveAttribute('href',
            '/case-intelligence?task_id=T&tab=forensic&report_id=report-a');
        expect(screen.getByText(/保留首次自主发现/)).toBeInTheDocument();
        expect(screen.getByText('材料不足，保留首次线索。')).toBeInTheDocument();
        expect(screen.getByText(/没有新增证据/)).toBeInTheDocument();
        fireEvent.click(screen.getAllByText('查看 m0001 冻结材料')[0]);
        expect(screen.getByRole('dialog')).toHaveTextContent(source.text);
    });
});
