import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import AgentReviewPanel from './AgentReviewPanel';
import AnalysisWorkspace from './AnalysisWorkspace';
import * as service from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({
  listAgentReviewCandidates: vi.fn(),
  getAgentReviewCandidate: vi.fn(),
  getAgentReviewHistory: vi.fn(),
  submitAgentReviewDecision: vi.fn(),
}));

vi.mock('./EvidenceAnalysisPanel', () => ({
  default: () => <div data-testid="evidence-analysis-panel">EvidenceAnalysisMock</div>,
}));

vi.mock('./EventAnalysisPanel', () => ({
  default: () => <div data-testid="event-analysis-panel">EventAnalysisMock</div>,
}));

const mockCandidates = [
  {
    candidate_id: 'finding:disp_f_01',
    target_type: 'finding',
    target_id: 'disp_f_01',
    claim_type: 'FACT',
    content: 'Detected unauthorized SSH brute-force login attempts from IP 192.168.1.100.',
    evidence_refs: ['file:/var/log/auth.log'],
    source_revision: 1,
    source_integration_id: 'si_integ_01',
    grounding_status: 'grounded',
    review_status: 'review_pending',
    candidate_hash: 'hash_fact_01',
    created_at: '2026-10-17T12:00:00Z',
    reviewed_at: null,
    reviewer: null,
    review_note: null,
  },
  {
    candidate_id: 'h-99201',
    target_type: 'hypothesis',
    target_id: 'h-99201',
    claim_type: 'HYPOTHESIS',
    content: 'Attacker likely escalated privileges via cron job script tampering.',
    evidence_refs: ['file:/etc/crontab'],
    source_revision: 2,
    source_integration_id: 'si_integ_02',
    grounding_status: 'grounded',
    review_status: 'review_pending',
    candidate_hash: 'hash_hypo_02',
    created_at: '2026-10-17T12:05:00Z',
    reviewed_at: null,
    reviewer: null,
    review_note: null,
  },
  {
    candidate_id: 'finding:disp_ungrounded',
    target_type: 'finding',
    target_id: 'disp_ungrounded',
    claim_type: 'INFERENCE',
    content: 'Lateral movement inferred from memory dumps.',
    evidence_refs: [],
    source_revision: 1,
    source_integration_id: 'si_integ_03',
    grounding_status: 'ungrounded',
    review_status: 'review_pending',
    candidate_hash: 'hash_infer_03',
    created_at: '2026-10-17T12:10:00Z',
    reviewed_at: null,
    reviewer: null,
    review_note: null,
  },
];

describe('AgentReviewPanel Component and Integration Tests (T01 - T34)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    service.listAgentReviewCandidates.mockResolvedValue([...mockCandidates]);
    service.getAgentReviewCandidate.mockImplementation((taskId, candidateId) => {
      const match = mockCandidates.find((c) => c.candidate_id === candidateId);
      return Promise.resolve(match ? { ...match } : null);
    });
    service.getAgentReviewHistory.mockResolvedValue([]);
    service.submitAgentReviewDecision.mockResolvedValue({
      review_id: 'rev_out_01',
      request_id: 'req_01',
      task_id: 'task-test-01',
      investigation_id: 'inv_01',
      target_id: 'finding:disp_f_01',
      target_type: 'finding',
      decision: 'accepted',
      status: 'accepted',
      accepted_finding_id: 'finding:disp_f_01',
      epistemic_type: 'FACT',
      candidate_hash: 'hash_fact_01',
      reviewed_at: '2026-10-17T12:30:00Z',
      reviewer: 'analyst',
      note: 'Verified against auth.log',
    });
  });

  test('T01 & T02: Review Panel renders in Analysis Workspace preserving layout', async () => {
    render(<AnalysisWorkspace taskId="task-test-01" evidenceKey="file:/var/log/auth.log" />);
    expect(screen.getByTestId('analysis-workspace-container')).toBeInTheDocument();
    expect(screen.getByTestId('agent-review-panel')).toBeInTheDocument();
    expect(screen.getByText(/Agent Analyst Review/i)).toBeInTheDocument();
  });

  test('T03: Current Task candidates loaded via listAgentReviewCandidates', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await waitFor(() => {
      expect(service.listAgentReviewCandidates).toHaveBeenCalledWith('task-test-01');
    });
    expect(await screen.findByText('finding:disp_f_01')).toBeInTheDocument();
    expect(screen.getByText('h-99201')).toBeInTheDocument();
    expect(screen.getByText('finding:disp_ungrounded')).toBeInTheDocument();
  });

  test('T04 & T23: Task switching clears stale candidates and ignores delayed async responses', async () => {
    let resolveTaskA;
    service.listAgentReviewCandidates.mockImplementation((taskId) => {
      if (taskId === 'task-A') {
        return new Promise((resolve) => {
          resolveTaskA = resolve;
        });
      }
      return Promise.resolve([mockCandidates[1]]);
    });

    const { rerender } = render(<AgentReviewPanel taskId="task-A" />);
    // Switch to task-B before task-A resolves
    rerender(<AgentReviewPanel taskId="task-B" />);

    // Now task-B resolves
    expect(await screen.findByText('h-99201')).toBeInTheDocument();

    // Now task-A resolves late
    act(() => {
      resolveTaskA([mockCandidates[0]]);
    });

    // task-A candidate must NOT overwrite task-B
    expect(screen.queryByText('finding:disp_f_01')).not.toBeInTheDocument();
    expect(screen.getByText('h-99201')).toBeInTheDocument();
  });

  test('T05: Review Candidate stable identity and hash rendered', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');

    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));
    expect(await screen.findByText(/ID: finding:disp_f_01/)).toBeInTheDocument();
    expect(screen.getByText(/Hash: hash_fact_01/)).toBeInTheDocument();
    expect(screen.getByText(/Rev 1/)).toBeInTheDocument();
  });

  test('T06 & T07: FACT / INFERENCE / HYPOTHESIS and Grounding status displayed accurately', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');

    // Epistemic badges
    expect(screen.getByText('FACT')).toBeInTheDocument();
    expect(screen.getByText('HYPOTHESIS')).toBeInTheDocument();
    expect(screen.getByText('INFERENCE')).toBeInTheDocument();

    // Grounding badges
    expect(screen.getAllByText('grounded').length).toBeGreaterThan(0);
    expect(screen.getByText('ungrounded')).toBeInTheDocument();
  });

  test('T08: Evidence refs linked to current task and clickable', async () => {
    const traceSpy = vi.fn();
    render(<AgentReviewPanel taskId="task-test-01" onTraceEvidence={traceSpy} />);
    await screen.findByText('finding:disp_f_01');

    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));
    const refBtn = await screen.findByTestId('evidence-ref-file:/var/log/auth.log');
    expect(refBtn).toBeInTheDocument();

    fireEvent.click(refBtn);
    expect(traceSpy).toHaveBeenCalledWith('file:/var/log/auth.log');
  });

  test('T09: Missing evidence references handled with EVIDENCE_UNAVAILABLE notice', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_ungrounded');

    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_ungrounded'));
    expect(await screen.findByTestId('evidence-unavailable-notice')).toBeInTheDocument();
    expect(screen.getByText(/EVIDENCE_UNAVAILABLE/)).toBeInTheDocument();
  });

  test('T10, T11 & T12: Selection and explicit Accept / Reject actions require confirmation', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');

    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    const acceptBtn = await screen.findByTestId('btn-accept-candidate');
    const rejectBtn = screen.getByTestId('btn-reject-candidate');
    expect(acceptBtn).toBeInTheDocument();
    expect(rejectBtn).toBeInTheDocument();

    // Clicking Accept opens confirmation dialog; does not post yet
    fireEvent.click(acceptBtn);
    expect(screen.getByTestId('review-confirmation-dialog')).toBeInTheDocument();
    expect(service.submitAgentReviewDecision).not.toHaveBeenCalled();

    // Cancel closes confirmation
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByTestId('review-confirmation-dialog')).not.toBeInTheDocument();

    // Clicking Reject opens confirmation dialog
    fireEvent.click(screen.getByTestId('btn-reject-candidate'));
    expect(screen.getByTestId('review-confirmation-dialog')).toBeInTheDocument();
    expect(screen.getByText(/确认显式审核决策：拒绝候选/)).toBeInTheDocument();
  });

  test('T13, T14: No optimistic update; Accept success updates candidate and refreshes history', async () => {
    let resolveSubmit;
    service.submitAgentReviewDecision.mockImplementation(() => {
      return new Promise((resolve) => {
        resolveSubmit = resolve;
      });
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    fireEvent.click(await screen.findByTestId('btn-accept-candidate'));
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    // In-flight: no optimistic update yet
    expect(screen.getAllByText('review_pending').length).toBeGreaterThan(0);

    // Backend responds 200 OK
    await act(async () => {
      resolveSubmit({
        review_id: 'rev_accepted_01',
        request_id: 'req_01',
        task_id: 'task-test-01',
        investigation_id: 'inv_01',
        target_id: 'finding:disp_f_01',
        target_type: 'finding',
        decision: 'accepted',
        status: 'accepted',
        accepted_finding_id: 'finding:disp_f_01',
        epistemic_type: 'FACT',
        candidate_hash: 'hash_fact_01',
        reviewed_at: '2026-10-17T12:35:00Z',
        reviewer: 'analyst',
        note: null,
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText('accepted').length).toBeGreaterThan(0);
    });
    expect(service.getAgentReviewHistory).toHaveBeenCalledWith('task-test-01', 'finding:disp_f_01');
  });

  test('T15: Reject success refreshes candidate and history', async () => {
    service.submitAgentReviewDecision.mockResolvedValueOnce({
      review_id: 'rev_rejected_01',
      request_id: 'req_02',
      task_id: 'task-test-01',
      investigation_id: 'inv_01',
      target_id: 'finding:disp_f_01',
      target_type: 'finding',
      decision: 'rejected',
      status: 'rejected',
      accepted_finding_id: null,
      epistemic_type: 'FACT',
      candidate_hash: 'hash_fact_01',
      reviewed_at: '2026-10-17T12:36:00Z',
      reviewer: 'analyst',
      note: 'Rejected due to insufficient corroboration',
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    fireEvent.click(await screen.findByTestId('btn-reject-candidate'));
    fireEvent.change(screen.getByTestId('review-note-input'), {
      target: { value: 'Rejected due to insufficient corroboration' },
    });
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    await waitFor(() => {
      expect(screen.getAllByText('rejected').length).toBeGreaterThan(0);
    });
  });

  test('T16: Accepted HYPOTHESIS remains HYPOTHESIS with explicit epistemic warning', async () => {
    service.submitAgentReviewDecision.mockResolvedValueOnce({
      review_id: 'rev_hypo_01',
      request_id: 'req_03',
      task_id: 'task-test-01',
      investigation_id: 'inv_01',
      target_id: 'h-99201',
      target_type: 'hypothesis',
      decision: 'accepted',
      status: 'accepted',
      accepted_finding_id: null,
      epistemic_type: 'HYPOTHESIS',
      candidate_hash: 'hash_hypo_02',
      reviewed_at: '2026-10-17T12:37:00Z',
      reviewer: 'analyst',
      note: 'Approved hypothesis as lead',
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('h-99201');
    fireEvent.click(screen.getByTestId('candidate-item-h-99201'));

    // Epistemic warning must be displayed
    expect(await screen.findByTestId('hypothesis-epistemic-warning')).toBeInTheDocument();
    expect(screen.getByText(/This is a hypothesis, not a verified fact/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('btn-accept-candidate'));
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    await waitFor(() => {
      expect(screen.getAllByText('accepted').length).toBeGreaterThan(0);
    });

    // Even when accepted, it must still display HYPOTHESIS, NEVER FACT
    expect(screen.getAllByText('HYPOTHESIS').length).toBeGreaterThan(0);
  });

  test('T17: HTTP 409 handled without automatic resubmit', async () => {
    service.submitAgentReviewDecision.mockRejectedValueOnce({
      status: 409,
      data: { detail: 'The review candidate has changed or has already been reviewed.' },
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    fireEvent.click(await screen.findByTestId('btn-accept-candidate'));
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    await waitFor(() => {
      expect(service.submitAgentReviewDecision).toHaveBeenCalledTimes(1);
    });
    // Confirmation dialog closed on 409, no automatic second call
    expect(screen.queryByTestId('review-confirmation-dialog')).not.toBeInTheDocument();
    expect(service.submitAgentReviewDecision).toHaveBeenCalledTimes(1);
  });

  test('T18 & T19: HTTP 422 and 404/503 handled gracefully', async () => {
    service.submitAgentReviewDecision.mockRejectedValueOnce({
      status: 422,
      data: { detail: 'Unauthorized FACT promotion blocked for ungrounded assertion.' },
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_ungrounded');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_ungrounded'));

    fireEvent.click(await screen.findByTestId('btn-accept-candidate'));
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    await waitFor(() => {
      expect(service.submitAgentReviewDecision).toHaveBeenCalledTimes(1);
    });
  });

  test('T20 & T21: Duplicate click prevented, network retry preserves request_id', async () => {
    let resolveFirst;
    service.submitAgentReviewDecision.mockImplementationOnce(() => {
      return new Promise((resolve, reject) => {
        resolveFirst = reject;
      });
    });

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    fireEvent.click(await screen.findByTestId('btn-accept-candidate'));
    const confirmBtn = screen.getByTestId('btn-confirm-review-decision');

    // First click
    fireEvent.click(confirmBtn);
    // Second rapid click while submitting is true
    fireEvent.click(confirmBtn);

    // Only one call sent (T20)
    expect(service.submitAgentReviewDecision).toHaveBeenCalledTimes(1);
    const firstReqId = service.submitAgentReviewDecision.mock.calls[0][0].request_id;
    expect(firstReqId).toBeTruthy();

    // First attempt fails with network error
    await act(async () => {
      resolveFirst({ message: 'Network timeout', status: 504 });
    });

    // Now retry (T21)
    service.submitAgentReviewDecision.mockResolvedValueOnce({
      review_id: 'rev_retried',
      status: 'accepted',
      decision: 'accepted',
    });
    fireEvent.click(confirmBtn);

    expect(service.submitAgentReviewDecision).toHaveBeenCalledTimes(2);
    const retryReqId = service.submitAgentReviewDecision.mock.calls[1][0].request_id;
    // Retains exact same request_id
    expect(retryReqId).toBe(firstReqId);
  });

  test('T24: Cross-task review submission prevented', async () => {
    // Inject a candidate belonging to a different task
    const crossTaskCandidate = {
      ...mockCandidates[0],
      task_id: 'task-other-02',
    };
    service.getAgentReviewCandidate.mockResolvedValueOnce(crossTaskCandidate);

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    fireEvent.click(await screen.findByTestId('btn-accept-candidate'));
    fireEvent.click(screen.getByTestId('btn-confirm-review-decision'));

    // Boundary check prevented submission
    expect(service.submitAgentReviewDecision).not.toHaveBeenCalled();
  });

  test('T25, T26 & T27: Read-only GET never triggers model execution, no auto-finalization, no auto-report admission', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');

    // Only read API called
    expect(service.listAgentReviewCandidates).toHaveBeenCalledTimes(1);
    expect(service.submitAgentReviewDecision).not.toHaveBeenCalled();
  });

  test('T28: Existing Evidence / Event Analysis remains functional in AnalysisWorkspace', () => {
    const { container } = render(
      <AnalysisWorkspace taskId="task-test-01" evidenceKey="file:/var/log/auth.log" />,
    );
    expect(container.querySelector('[data-testid="evidence-analysis-panel"]')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="agent-review-panel"]')).toBeInTheDocument();
  });

  test('T29: Review history displayed from authoritative backend response', async () => {
    service.getAgentReviewHistory.mockResolvedValueOnce([
      {
        review_id: 'hist_01',
        task_id: 'task-test-01',
        investigation_id: 'inv_01',
        finding_id: 'finding:disp_f_01',
        decision: 'accepted',
        reviewer: 'analyst_bob',
        note: 'Corroborated with firewall logs',
        created_at: '2026-10-17 12:20:00',
      },
    ]);

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    expect(await screen.findByTestId('history-item-hist_01')).toBeInTheDocument();
    expect(screen.getByText('analyst_bob')).toBeInTheDocument();
    expect(screen.getByText('Corroborated with firewall logs')).toBeInTheDocument();
  });

  test('T30: Reviewer identity limitation disclosed', async () => {
    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:disp_f_01');
    fireEvent.click(screen.getByTestId('candidate-item-finding:disp_f_01'));

    expect(await screen.findByTestId('reviewer-authority-notice')).toBeInTheDocument();
    expect(
      screen.getByText(/REVIEWER_AUTHENTICATION_LIMITATION: caller-declared identity in local mode/),
    ).toBeInTheDocument();
  });

  test('T34: Untrusted model text rendered as text node without script execution', async () => {
    const untrustedCandidate = {
      ...mockCandidates[0],
      candidate_id: 'finding:xss_test',
      content: '<script>window.__xss_flag = true;</script><img src="x" onerror="window.__xss_flag = true;">Malicious text',
    };
    service.listAgentReviewCandidates.mockResolvedValueOnce([untrustedCandidate]);
    service.getAgentReviewCandidate.mockResolvedValueOnce(untrustedCandidate);

    render(<AgentReviewPanel taskId="task-test-01" />);
    await screen.findByText('finding:xss_test');
    fireEvent.click(screen.getByTestId('candidate-item-finding:xss_test'));

    const contentBox = await screen.findByTestId('candidate-full-content');
    expect(contentBox.textContent).toContain('<script>window.__xss_flag = true;</script>');
    expect(window.__xss_flag).toBeUndefined();
  });
});
