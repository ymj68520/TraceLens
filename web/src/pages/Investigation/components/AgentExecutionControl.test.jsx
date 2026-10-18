import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import AgentExecutionControl from './AgentExecutionControl';
import * as featuresService from '../../../services/featuresService';
import * as investigationService from '../../../services/investigationService';

vi.mock('../../../services/featuresService', () => ({
  fetchFeatures: vi.fn(),
}));

vi.mock('../../../services/investigationService', () => ({
  executeAgentCycle: vi.fn(),
  getAgentState: vi.fn(),
}));

describe('AgentExecutionControl Component Tests', () => {
  const mockTaskId = 'test-task-123';

  const mockStateInitial = {
    task_id: mockTaskId,
    investigation_id: 'inv_abc',
    working_state_revision: 1,
    working_state_hash: 'hash_rev_1',
    objective: 'Initial Forensics',
    agent_execution_status: 'idle',
    questions_count: 2,
    findings_count: 3,
    hypotheses_count: 1,
    active_delegations_count: 0,
    latest_trajectory_ref: 'plan:1',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    featuresService.fetchFeatures.mockResolvedValue({
      agent_execution_enabled: true,
    });
    investigationService.getAgentState.mockResolvedValue(mockStateInitial);
    investigationService.executeAgentCycle.mockResolvedValue({
      cycle_id: 'cyc_001',
      task_id: mockTaskId,
      investigation_id: 'inv_abc',
      run_id: 'run_001',
      starting_revision: 1,
      ending_revision: 2,
      integration_status: 'committed',
      integration_revision: 2,
      delegation_ids: ['del_001'],
      run_stop_reason: 'plan_completed',
      warnings: [],
      limitations: [],
    });
  });

  test('T01: Renders agent state metrics and revision badge', async () => {
    render(<AgentExecutionControl taskId={mockTaskId} />);

    await waitFor(() => {
      expect(screen.getByTestId('agent-state-revision')).toHaveTextContent('Rev 1');
    });

    expect(screen.getByText('Agent 调查执行 (Agent v0)')).toBeInTheDocument();
    expect(screen.getByTestId('agent-execution-status-badge')).toHaveTextContent('idle');
    expect(screen.getByTestId('agent-state-metrics')).toBeInTheDocument();
  });

  test('T02: Button disabled and notice rendered when agent_execution_enabled is false', async () => {
    featuresService.fetchFeatures.mockResolvedValue({
      agent_execution_enabled: false,
    });

    render(<AgentExecutionControl taskId={mockTaskId} />);

    await waitFor(() => {
      expect(screen.getByTestId('btn-start-agent-cycle')).toBeDisabled();
    });

    expect(screen.getByTestId('agent-execution-disabled-notice')).toBeInTheDocument();
  });

  test('T03: Triggers executeAgentCycle and fires onCycleCompleted callback on success', async () => {
    const handleCompleted = vi.fn();

    render(
      <AgentExecutionControl
        taskId={mockTaskId}
        onCycleCompleted={handleCompleted}
      />
    );

    const startBtn = await screen.findByTestId('btn-start-agent-cycle');
    expect(startBtn).not.toBeDisabled();

    // Click start cycle
    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(investigationService.executeAgentCycle).toHaveBeenCalledTimes(1);
    const callArgs = investigationService.executeAgentCycle.mock.calls[0][0];
    expect(callArgs.task_id).toBe(mockTaskId);
    expect(callArgs.expected_working_state_revision).toBe(1);

    await waitFor(() => {
      expect(handleCompleted).toHaveBeenCalledWith(
        expect.objectContaining({
          cycle_id: 'cyc_001',
          ending_revision: 2,
        })
      );
    });
  });

  test('T04: Duplicate clicks prevented while execution is in-flight', async () => {
    let resolveCycle;
    investigationService.executeAgentCycle.mockImplementation(
      () => new Promise((resolve) => { resolveCycle = resolve; })
    );

    render(<AgentExecutionControl taskId={mockTaskId} />);

    const startBtn = await screen.findByTestId('btn-start-agent-cycle');

    // Click first time
    await act(async () => {
      fireEvent.click(startBtn);
    });

    // Should be in executing state
    expect(startBtn).toBeDisabled();
    expect(screen.getByText('执行中...')).toBeInTheDocument();

    // Click again while in-flight
    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(investigationService.executeAgentCycle).toHaveBeenCalledTimes(1);

    // Resolve the cycle
    await act(async () => {
      resolveCycle({
        cycle_id: 'cyc_002',
        starting_revision: 1,
        ending_revision: 2,
      });
    });

    await waitFor(() => {
      expect(startBtn).not.toBeDisabled();
    });
  });

  test('T05: Displays error banner and retains request_id on execution failure', async () => {
    investigationService.executeAgentCycle.mockRejectedValue({
      data: { detail: 'Model timeout during cycle execution' },
      message: 'Model timeout',
    });

    render(<AgentExecutionControl taskId={mockTaskId} />);

    const startBtn = await screen.findByTestId('btn-start-agent-cycle');

    await act(async () => {
      fireEvent.click(startBtn);
    });

    const errorBanner = await screen.findByTestId('agent-execution-error-banner');
    expect(errorBanner).toHaveTextContent('Model timeout during cycle execution');
    expect(screen.getByText('重试 (Retry)')).toBeInTheDocument();

    // Verify stable request_id was preserved
    const req1 = investigationService.executeAgentCycle.mock.calls[0][0].request_id;

    // Click retry
    investigationService.executeAgentCycle.mockResolvedValueOnce({
      cycle_id: 'cyc_retry',
      starting_revision: 1,
      ending_revision: 2,
    });

    await act(async () => {
      fireEvent.click(screen.getByText('重试 (Retry)'));
    });

    expect(investigationService.executeAgentCycle).toHaveBeenCalledTimes(2);
    const req2 = investigationService.executeAgentCycle.mock.calls[1][0].request_id;
    expect(req2).toBe(req1); // Must retain exact same request_id on retry
  });

  test('T06: Manual refresh button re-fetches agent state', async () => {
    render(<AgentExecutionControl taskId={mockTaskId} />);

    await waitFor(() => {
      expect(investigationService.getAgentState).toHaveBeenCalledWith(mockTaskId, null);
    });

    const refreshBtn = screen.getByTestId('btn-refresh-agent-state');
    await act(async () => {
      fireEvent.click(refreshBtn);
    });

    expect(investigationService.getAgentState).toHaveBeenCalledTimes(2);
  });
});
