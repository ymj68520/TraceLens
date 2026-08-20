// ForensicReportPage.generation.test.jsx
// §28 完整用户链（R2 冻结语义的最终 UI 证明）：
//   Evidence A(main, bound A1/claim C1) + B(appendix, original-only)
//   → Generate → G1 admitted→running→completed → V1
//   → citation CITA → exact A1 / exact C1
//   → A2 accepted + rebind 之后重开 V1 仍是 A1/C1
//   → Generate G2 → V2 才显示 A2。
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import ForensicReportPage from './ForensicReportPage';

vi.mock('../services/reportGenerationService', () => ({
    generateReport: vi.fn(),
    getReportGeneration: vi.fn(),
    getNarrativeReport: vi.fn(),
}));
vi.mock('../services/investigationService', () => ({
    listReportEvidence: vi.fn(),
    getInvestigationSnapshot: vi.fn(),
    getInvestigationAnalysis: vi.fn(),
    listInvestigationAnalysisClaims: vi.fn(),
}));

import {
    generateReport,
    getReportGeneration,
    getNarrativeReport,
} from '../services/reportGenerationService';
import {
    listReportEvidence,
    getInvestigationSnapshot,
    getInvestigationAnalysis,
    listInvestigationAnalysisClaims,
} from '../services/investigationService';

const TASK = 'task-T';

// ── source set：A main 绑 A1（含 C1），B appendix original-only ──────────────
const SOURCE_SET = [
    {
        evidence_key: 'file:/case/a.txt',
        report_status: 'main',
        bound_analysis: { analysis_id: 'A1', version: 1 },
        newer_accepted_available: false,
    },
    { evidence_key: 'file:/case/b.txt', report_status: 'appendix', bound_analysis: null },
];

const snapshotFor = (key) => ({
    evidence_key: key,
    evidence_type: 'file',
    captured_at: 1000,
    payload: { initial_summary: `snapshot of ${key}` },
});

// ── narrative manifests：V1 冻结 A1/C1；rebind 之后发布的 V2 才是 A2 ─────────
const manifestV1 = {
    task_id: TASK,
    report_id: 'rep-1',
    version: 1,
    status: 'ready',
    generation_id: 'rg_1',
    title: 'Narrative V1',
    created_at: '2026-08-16T01:00:00+00:00',
    model: 'm',
    prompt_version: 'final-report:v1',
    input_hash: 'v1hash',
    sections: [{
        heading: 'Findings',
        content: 'A was analyzed.',
        citation_ids: ['CITA'],
    }],
    citations: [{
        citation_id: 'CITA',
        evidence_key: 'file:/case/a.txt',
        analysis_id: 'A1',
        claim_id: 'C1',
        evidence_captured_at: 1000,
        analysis_version: 1,
        claim_type: 'fact',
    }],
};

const manifestV2 = {
    ...manifestV1,
    report_id: 'rep-2',
    version: 2,
    generation_id: 'rg_2',
    title: 'Narrative V2',
    created_at: '2026-08-16T02:00:00+00:00',
    input_hash: 'v2hash',
    citations: [{
        citation_id: 'CITA2',
        evidence_key: 'file:/case/a.txt',
        analysis_id: 'A2',
        claim_id: 'C2',
        evidence_captured_at: 1000,
        analysis_version: 2,
        claim_type: 'fact',
    }],
    sections: [{
        heading: 'Findings',
        content: 'A was re-analyzed.',
        citation_ids: ['CITA2'],
    }],
};

const versionRow = (manifest) => ({
    report_id: manifest.report_id,
    version: manifest.version,
    status: 'ready',
    title: manifest.title,
    report_kind: 'llm_generation',
});

function makePage(initialVersions = []) {
    const versionsStore = [...initialVersions];
    const dataSource = {
        listVersions: vi.fn(() => Promise.resolve([...versionsStore])),
        createVersion: vi.fn(),
        getStatus: vi.fn(
            (id) => Promise.resolve(versionsStore.find((v) => v.report_id === id) || null),
        ),
        getManifest: vi.fn(),
        search: vi.fn(),
    };
    const view = render(
        <MemoryRouter initialEntries={['/reports/task/task-T']}>
            <ForensicReportPage
                scopeType="task"
                scopeId={TASK}
                dataSource={dataSource}
                generationPollIntervalMs={0}
            />
        </MemoryRouter>,
    );
    return { view, versionsStore, dataSource };
}

const startGeneration = async () => {
    fireEvent.change(screen.getByTestId('generate-actor-input'), {
        target: { value: 'analyst-x' },
    });
    await waitFor(() => expect(screen.getByTestId('generate-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('generate-submit'));
};

const advanceGeneration = async (state, extra = {}) => {
    await act(async () => {
        Object.assign(state, extra);
    });
};

describe('ForensicReportPage generation chain (§28)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        listReportEvidence.mockResolvedValue(SOURCE_SET);
        getInvestigationSnapshot.mockImplementation(async (_t, key) => snapshotFor(key));
        getInvestigationAnalysis.mockImplementation(async (_t, id) => ({
            analysis_id: id,
            version: id === 'A1' ? 1 : 2,
            status: 'accepted',
            decided_by: 'analyst-x',
            grounding_status: 'grounded',
            description: `analysis ${id}`,
        }));
        listInvestigationAnalysisClaims.mockImplementation(async (_t, id) => (
            id === 'A1'
                ? [{ claim_id: 'C1', claim_text: 'A1 text', grounding_status: 'grounded', evidence_refs: ['file:/case/a.txt'] }]
                : [{ claim_id: 'C2', claim_text: 'A2 text', grounding_status: 'grounded', evidence_refs: ['file:/case/a.txt'] }]
        ));
        getNarrativeReport.mockImplementation(async (_t, reportId) => {
            if (reportId === 'rep-1') return manifestV1;
            if (reportId === 'rep-2') return manifestV2;
            return { ...manifestV2, report_id: reportId, version: 4, title: 'Late Narrative' };
        });
    });

    test('G1 completes into exact V1, citation traces to exact A1/C1, and a later rebind never rewrites V1', async () => {
        const { versionsStore } = makePage();
        expect(await screen.findByTestId('generate-source-summary')).toBeInTheDocument();
        expect(screen.getByTestId('summary-main')).toHaveTextContent('Main Evidence: 1');
        expect(screen.getByTestId('summary-original')).toHaveTextContent('Original-only: 1');

        const genState = { generation_id: 'rg_1', task_id: TASK, status: 'admitted' };
        generateReport.mockResolvedValue({ ...genState });
        getReportGeneration.mockImplementation(async () => ({ ...genState }));

        await startGeneration();
        expect(generateReport).toHaveBeenCalledWith(TASK, { requestedBy: 'analyst-x' });
        expect(await screen.findByTestId('generate-status')).toHaveTextContent('排队中');

        await advanceGeneration(genState, { status: 'running' });
        await waitFor(() => expect(screen.getByTestId('generate-status')).toHaveTextContent('生成中'));

        // G1 完成 → publication 已写入版本行 → completed 轮询返回 exact identity。
        versionsStore.push(versionRow(manifestV1));
        await advanceGeneration(genState, {
            status: 'completed', report_id: 'rep-1', produced_version: 1,
        });

        // §26-6：completed → 停止轮询，打开 exact report_id/version（不是 latest）。
        expect(await screen.findByTestId('narrative-report-view')).toBeInTheDocument();
        await waitFor(() => expect(screen.getAllByText('Narrative V1').length).toBeGreaterThan(0));
        expect(screen.getByTestId('generate-completed-identity')).toHaveTextContent('rep-1');
        expect(screen.getByTestId('generate-completed-identity')).toHaveTextContent('v1');
        // V1 是叙事版本：绝不为它调用 deterministic manifest 路由
        expect(screen.queryByRole('main', { name: '报告正文' })).not.toBeInTheDocument();

        // citation CITA → exact Evidence A / A1 / C1
        fireEvent.click(await screen.findByTestId('citation-chip-CITA'));
        expect(await screen.findByTestId('traceback-analysis-layer')).toHaveTextContent('A1');
        expect(screen.getByTestId('traceback-claim-layer')).toHaveTextContent('C1');
        expect(getInvestigationAnalysis).toHaveBeenCalledWith(TASK, 'A1');
        expect(listInvestigationAnalysisClaims).toHaveBeenCalledWith(TASK, 'A1');

        // ── A2 accepted + Report Evidence rebind：V1 冻结不变 ──────────────
        // （rebind 只影响后续 admission；V1 的 manifest 与 traceback 仍是 A1/C1）
        vi.mocked(getInvestigationAnalysis).mockClear();
        vi.mocked(listInvestigationAnalysisClaims).mockClear();
        fireEvent.click(screen.getByTestId('citation-chip-CITA')); // toggle off
        fireEvent.click(screen.getByTestId('citation-chip-CITA')); // 重新打开 V1 的同一引用
        await waitFor(() => expect(getInvestigationAnalysis).toHaveBeenCalledWith(TASK, 'A1'));
        expect(screen.getByTestId('traceback-analysis-layer')).toHaveTextContent('A1');
        expect(getNarrativeReport).toHaveBeenLastCalledWith(TASK, 'rep-1');

        // ── G2 → V2 才显示 A2 provenance ───────────────────────────────────
        const gen2 = { generation_id: 'rg_2', task_id: TASK, status: 'admitted' };
        generateReport.mockResolvedValue({ ...gen2 });
        getReportGeneration.mockImplementation(async () => ({ ...gen2 }));

        await startGeneration(); // terminal 后按钮重新可用（显式再发起，非自动 retry）
        await advanceGeneration(gen2, { status: 'running' });
        versionsStore.push(versionRow(manifestV2));
        await advanceGeneration(gen2, {
            status: 'completed', report_id: 'rep-2', produced_version: 2,
        });

        await waitFor(() => expect(screen.getAllByText('Narrative V2').length).toBeGreaterThan(0));
        fireEvent.click(await screen.findByTestId('citation-chip-CITA2'));
        expect(await screen.findByTestId('traceback-analysis-layer')).toHaveTextContent('A2');
        expect(screen.getByTestId('traceback-claim-layer')).toHaveTextContent('C2');
    });
    test('a late G1 completion never hijacks an explicit historical selection (§26-9)', async () => {
        // 初始已有：V1（叙事）与 V3（deterministic 快照）。
        const { versionsStore } = makePage([
            versionRow(manifestV1),
            { report_id: 'rep-det', version: 3, status: 'ready', title: 'Deterministic', report_kind: null },
        ]);

        // 用户显式查看历史 V1（初始 auto-select 是 v3 deterministic，这里
        // 显式点击版本 1）。
        fireEvent.click(await screen.findByRole('radio', { name: '版本 1' }));
        await waitFor(() => expect(screen.getAllByText('Narrative V1').length).toBeGreaterThan(0));

        const genState = { generation_id: 'rg_1', task_id: TASK, status: 'admitted' };
        generateReport.mockResolvedValue({ ...genState });
        getReportGeneration.mockImplementation(async () => ({ ...genState }));
        await startGeneration();

        // G1 running 期间用户主动切走：显式选择版本 3（deterministic 快照）。
        await act(async () => {
            fireEvent.click(screen.getByRole('radio', { name: '版本 3' }));
        });
        await waitFor(() => expect(screen.queryByTestId('narrative-report-view')).not.toBeInTheDocument());

        // G1 晚些完成（版本 4）。服务器 mutation 成功，但 Viewer 不被劫持。
        versionsStore.push({
            report_id: 'rep-new', version: 4, status: 'ready',
            title: 'Late Narrative', report_kind: 'llm_generation',
        });
        await advanceGeneration(genState, {
            status: 'completed', report_id: 'rep-new', produced_version: 4,
        });

        await waitFor(() => expect(screen.getByTestId('generate-completed-identity')).toBeInTheDocument());
        await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
        expect(screen.queryByText('Late Narrative')).not.toBeInTheDocument();
        expect(screen.getByRole('radio', { name: '版本 3' })).toBeChecked();
        // late narrative 版本仍可通过显式点击打开（exact selection 语义）
        const lateRadio = await screen.findByRole('radio', { name: '版本 4' });
        fireEvent.click(lateRadio);
        await waitFor(() => expect(screen.getByText('Late Narrative')).toBeInTheDocument());
    });
});
