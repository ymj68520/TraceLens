import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import GenerateReportPanel from './GenerateReportPanel';

const binding = (key, status, { bound = null, newer = false } = {}) => ({
    evidence_key: key,
    report_status: status,
    bound_analysis: bound,
    newer_accepted_available: newer,
});

// §26-1 的 source set：main=2、appendix=1、original-only=1、bound=2。
const SOURCE_SET = [
    binding('file:/case/a.txt', 'main', { bound: { analysis_id: 'A1', version: 1 } }),
    binding('file:/case/b.txt', 'main', { bound: { analysis_id: 'A2', version: 2 } }),
    binding('file:/case/c.txt', 'appendix'),
    binding('file:/case/excluded.txt', 'excluded'),
];

function makePanel(overrides = {}) {
    const generate = vi.fn().mockResolvedValue({ generation_id: 'rg_1', status: 'admitted' });
    const onComplete = vi.fn();
    const utils = render(
        <GenerateReportPanel
            taskId="t1"
            evidenceLoader={vi.fn().mockResolvedValue(SOURCE_SET)}
            generate={generate}
            fetchGeneration={vi.fn()}
            onComplete={onComplete}
            {...overrides}
        />,
    );
    return { generate, onComplete, ...utils };
}

const submit = async () => {
    fireEvent.change(screen.getByTestId('generate-actor-input'), { target: { value: 'analyst-x' } });
    await waitFor(() => expect(screen.getByTestId('generate-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('generate-submit'));
};

describe('GenerateReportPanel', () => {
    test('source summary reflects the explicit Report Evidence set (main=2 appendix=1 original=1 bound=2)', async () => {
        makePanel();
        expect(await screen.findByTestId('generate-source-summary')).toBeInTheDocument();
        expect(screen.getByTestId('summary-main')).toHaveTextContent('Main Evidence: 2');
        expect(screen.getByTestId('summary-appendix')).toHaveTextContent('Appendix Evidence: 1');
        expect(screen.getByTestId('summary-original')).toHaveTextContent('Original-only: 1');
        expect(screen.getByTestId('summary-bound')).toHaveTextContent('Bound accepted analyses: 2');
        // excluded 行不是 source set 的一部分
        expect(screen.queryByText(/excluded/)).not.toBeInTheDocument();
    });

    test('newer_accepted_available surfaces the frozen-binding hint without auto rebind', async () => {
        render(
            <GenerateReportPanel
                taskId="t1"
                evidenceLoader={vi.fn().mockResolvedValue([
                    binding('file:/case/a.txt', 'main', { bound: { analysis_id: 'A1', version: 1 }, newer: true }),
                ])}
                generate={vi.fn()}
                fetchGeneration={vi.fn()}
            />,
        );
        expect(await screen.findAllByTestId('newer-accepted-hint')).toHaveLength(1);
        expect(screen.getByText(/仍绑定历史版本/)).toBeInTheDocument();
    });

    test('Generate request carries exactly {task_id, requested_by} (§26-2)', async () => {
        const { generate } = makePanel();
        await submit();
        await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
        expect(generate).toHaveBeenCalledWith('t1', { requestedBy: 'analyst-x' });
    });

    test('rapid double-click produces exactly one admission (§26-3)', async () => {
        let release;
        const generate = vi.fn().mockReturnValue(new Promise((resolve) => { release = resolve; }));
        render(
            <GenerateReportPanel
                taskId="t1"
                evidenceLoader={vi.fn().mockResolvedValue(SOURCE_SET)}
                generate={generate}
                fetchGeneration={vi.fn()}
            />,
        );
        fireEvent.change(await screen.findByTestId('generate-actor-input'), { target: { value: 'analyst-x' } });
        await waitFor(() => expect(screen.getByTestId('generate-submit')).toBeEnabled());
        // 同一用户动作内的连击：同步 ref 防抖必须立即生效。
        fireEvent.click(screen.getByTestId('generate-submit'));
        fireEvent.click(screen.getByTestId('generate-submit'));
        fireEvent.click(screen.getByTestId('generate-submit'));
        await act(async () => { release({ generation_id: 'rg_1' }); });
        expect(generate).toHaveBeenCalledTimes(1);
    });

    test('HTTP admission failure is shown separately from durable generation failure (§26-7)', async () => {
        const generate = vi.fn().mockRejectedValue({ status: 409, data: { detail: 'task has no report evidence' } });
        render(
            <GenerateReportPanel
                taskId="t1"
                evidenceLoader={vi.fn().mockResolvedValue([])}
                generate={generate}
                fetchGeneration={vi.fn()}
            />,
        );
        await submit();
        expect(await screen.findByTestId('generate-admission-error')).toHaveTextContent('HTTP admission failure');
        expect(screen.getByText(/task has no report evidence/)).toBeInTheDocument();
        // durable 状态区不出现（admission 从未成功）
        expect(screen.queryByTestId('generate-status')).not.toBeInTheDocument();
    });

    test('empty source set shows explicit guidance instead of "all case information"', async () => {
        render(
            <GenerateReportPanel
                taskId="t1"
                evidenceLoader={vi.fn().mockResolvedValue([])}
                generate={vi.fn()}
                fetchGeneration={vi.fn()}
            />,
        );
        expect(await screen.findByTestId('summary-empty')).toBeInTheDocument();
        expect(screen.getByText(/基于当前显式 Report Evidence 集合/)).toBeInTheDocument();
    });
});
