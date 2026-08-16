import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import CitationTracebackPanel from './CitationTracebackPanel';

const ORIGINAL_ONLY = {
    citation_id: 'cit-b',
    evidence_key: 'file:/case/b.txt',
    analysis_id: null,
    claim_id: null,
    evidence_captured_at: 2000,
    analysis_version: null,
    claim_type: null,
};

const CLAIM_CITATION = {
    citation_id: 'cit-a',
    evidence_key: 'file:/case/a.txt',
    analysis_id: 'A1',
    claim_id: 'C1',
    evidence_captured_at: 1000,
    analysis_version: 3,
    claim_type: 'fact',
};

const SNAPSHOT = {
    evidence_key: 'file:/case/a.txt',
    captured_at: 1000,
    evidence_type: 'file',
    payload: { initial_summary: 'Hash list of system files.', initial_model: 'm0' },
};

const ANALYSIS_A1 = {
    analysis_id: 'A1',
    version: 3,
    status: 'accepted',
    decided_by: 'analyst-x',
    decided_at: '2026-08-15T00:00:00+00:00',
    grounding_status: 'grounded',
    description: 'Consistent timeline.',
};

function makeLoaders(overrides = {}) {
    return {
        snapshot: vi.fn().mockResolvedValue(SNAPSHOT),
        analysis: vi.fn().mockResolvedValue(ANALYSIS_A1),
        claims: vi.fn().mockResolvedValue([]),
        ...overrides,
    };
}

describe('CitationTracebackPanel', () => {
    test('citation with analysis/claim passes exact ids to the detail readers (§27-4)', async () => {
        const loaders = makeLoaders({
            claims: vi.fn().mockResolvedValue([
                { claim_id: 'C1', claim_text: 'Same text.', grounding_status: 'grounded', evidence_refs: ['file:/case/a.txt'] },
                { claim_id: 'C2', claim_text: 'Same text.', grounding_status: 'grounded', evidence_refs: [] },
            ]),
        });
        render(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={CLAIM_CITATION}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        expect(await screen.findByTestId('traceback-claim-layer')).toBeInTheDocument();
        expect(loaders.snapshot).toHaveBeenCalledWith('t1', 'file:/case/a.txt');
        expect(loaders.analysis).toHaveBeenCalledWith('t1', 'A1');
        expect(loaders.claims).toHaveBeenCalledWith('t1', 'A1');

        // §27-5：C1 与 C2 文本相同，但 manifest 引用 C1 —— 只按 exact
        // claim_id 取 C1，绝不做文本匹配。
        expect(screen.getByText(/C1/)).toBeInTheDocument();
        expect(screen.getByText('Same text.')).toBeInTheDocument();
        const claimCalls = loaders.claims.mock.calls;
        expect(claimCalls).toHaveLength(1);
    });

    test('original-only citation shows evidence only and never auto-attaches an analysis (§27-3/§17)', async () => {
        const loaders = makeLoaders();
        render(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={ORIGINAL_ONLY}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        expect(await screen.findByTestId('traceback-evidence-layer')).toBeInTheDocument();
        expect(screen.getByTestId('traceback-original-only')).toBeInTheDocument();
        expect(screen.queryByTestId('traceback-analysis-layer')).not.toBeInTheDocument();
        expect(screen.queryByTestId('traceback-claim-layer')).not.toBeInTheDocument();
        // current B 已有 accepted analysis 的场景也不会因此补读 analysis
        expect(loaders.analysis).not.toHaveBeenCalled();
        expect(loaders.claims).not.toHaveBeenCalled();
    });

    test('frozen identity stays visible when current investigation detail is unavailable (§27-7/§15)', async () => {
        const loaders = makeLoaders({ snapshot: vi.fn().mockRejectedValue({ status: 503 }) });
        render(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={CLAIM_CITATION}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        expect(await screen.findByTestId('traceback-enrichment-error')).toBeInTheDocument();
        expect(screen.getByText(/详细记录暂时不可读取/)).toBeInTheDocument();
        // frozen identity 层仍然完整展示，不判定引用不存在
        expect(screen.getByTestId('traceback-evidence-layer')).toHaveTextContent('file:/case/a.txt');
        expect(screen.getByTestId('traceback-analysis-layer')).toHaveTextContent('A1');
        expect(screen.getByTestId('traceback-claim-layer')).toHaveTextContent('C1');
    });

    test('a late response from another citation/task never lands in the current panel (§23)', async () => {
        let releaseSnapshot;
        const first = new Promise((resolve) => { releaseSnapshot = resolve; });
        const loaders = makeLoaders({ snapshot: vi.fn().mockReturnValueOnce(first).mockResolvedValue(SNAPSHOT) });
        const view = render(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={ORIGINAL_ONLY}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        // A citation detail pending → 切换到另一条 citation
        view.rerender(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={CLAIM_CITATION}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        releaseSnapshot({ evidence_key: 'file:/OTHER.txt', payload: { initial_summary: 'STALE' } });

        expect(await screen.findByTestId('traceback-analysis-layer')).toBeInTheDocument();
        await waitFor(() => expect(screen.queryByText('STALE')).not.toBeInTheDocument());
        expect(screen.queryByText('file:/OTHER.txt')).not.toBeInTheDocument();
    });

    test('three layers are visually and semantically distinct (Evidence Source / derived finding / derived claim)', async () => {
        const loaders = makeLoaders({
            claims: vi.fn().mockResolvedValue([
                { claim_id: 'C1', claim_text: 'Claim text.', grounding_status: 'grounded', evidence_refs: ['file:/case/a.txt'] },
            ]),
        });
        render(
            <CitationTracebackPanel
                taskId="t1"
                reportId="rep-1"
                citation={CLAIM_CITATION}
                onClose={() => {}}
                loaders={loaders}
            />,
        );
        expect(await screen.findByTestId('traceback-claim-layer')).toBeInTheDocument();
        expect(screen.getByText(/Evidence Source/i)).toBeInTheDocument();
        expect(screen.getByText(/analyst-accepted derived finding/i)).toBeInTheDocument();
        expect(screen.getByText(/derived claim/i)).toBeInTheDocument();
    });
});
