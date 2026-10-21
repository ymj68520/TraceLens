import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import AgentWorkbench from './AgentWorkbench';
import * as service from '../../services/investigationService';

vi.mock('../../services/featuresService', () => ({
  fetchFeatures: () => Promise.resolve({ agent_execution_enabled: true }),
}));

vi.mock('../../services/reportService', () => ({
  listReportVersions: vi.fn().mockResolvedValue([]),
}));

vi.mock('../../store/caseSlice', () => ({
  fetchCases: vi.fn(() => ({ type: 'cases/noop' })),
}));

vi.mock('../../store/taskSlice', () => ({
  fetchTasksSilent: vi.fn(() => ({ type: 'tasks/noop' })),
}));

vi.mock('../../services/investigationService', () => ({
  getAgentState: vi.fn(),
  getAgentTrajectory: vi.fn(),
  listAgentReviewCandidates: vi.fn(),
  getAgentReviewCandidate: vi.fn(),
  getAgentReviewHistory: vi.fn(),
  submitAgentReviewDecision: vi.fn(),
  executeAgentCycle: vi.fn(),
}));

vi.mock('../../components/common/ToastContext', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}));

const mockAgentState = {
  task_id: 'task-test-01',
  investigation_id: 'inv_wo_dian_002',
  working_state_revision: 2,
  working_state_hash: '9b0d47b287acc3384097316d04aae578422d5e0591b4ee6c590b3b001c4d26f9',
  objective: '涉诈投资平台（杀猪盘）窝点作案终端案：固定话术体系与赃款归集',
  agent_execution_status: 'idle',
  questions_count: 7,
  questions_summary: [
    { question_id: 'Q1', status: 'open' },
    { question_id: 'Q2', status: 'open' },
    { question_id: 'Q3', status: 'in_progress' },
    { question_id: 'q-61dff02c', status: 'open' },
    { question_id: 'q-ad56bfce', status: 'open' },
    { question_id: 'q-b856d85c', status: 'open' },
    { question_id: 'q-de74d9f4', status: 'open' },
  ],
  findings_count: 1,
  hypotheses_count: 1,
  active_delegations_count: 0,
  latest_trajectory_ref: 'runtime_recovered:196',
};

const mockCandidates = [
  {
    candidate_id: 'f-pillar1-scripts-01',
    target_type: 'finding',
    target_id: 'f-pillar1-scripts-01',
    claim_type: 'FACT',
    content: '磁盘根目录存在完整诈骗话术培训资料库（/话术/），包含《老师包装.txt》',
    evidence_refs: ['file:/话术/老师包装.txt'],
    source_revision: 2,
    grounding_status: 'grounded',
    review_status: 'accepted',
    candidate_hash: 'hash_fact_01',
    created_at: '2026-10-17T15:30:57.171447Z',
    reviewed_at: '2026-10-17T15:32:40.308884Z',
    reviewer: 'lead_forensic_analyst',
    review_note: 'Verified against E01 image',
  },
  {
    candidate_id: 'h-pillar6-cryptocoin-01',
    target_type: 'hypothesis',
    target_id: 'h-pillar6-cryptocoin-01',
    claim_type: 'HYPOTHESIS',
    content: '涉案人员使用 TrueCrypt 卷与境外 ETH 钱包进行赃款规避洗钱',
    evidence_refs: ['file:/TrueCrypt/volume.tc'],
    source_revision: 2,
    grounding_status: 'grounded',
    review_status: 'review_pending',
    candidate_hash: 'hash_hypo_01',
    created_at: '2026-10-17T15:35:00.000000Z',
  },
];

const mockTrajectoryEvents = [
  {
    seq: 1,
    event_id: 'evt-01',
    event_type: 'supervisor_planning_cycle_started',
    title: 'Supervisor 目标制定',
    description: '制定调查目标',
    created_at: '2026-10-17T15:30:00Z',
  },
  {
    seq: 2,
    event_id: 'evt-02',
    event_type: 'grounding_validator_passed',
    title: 'GroundingValidator 接地校验',
    description: '事实校验通过',
    created_at: '2026-10-17T15:31:00Z',
  },
];

function renderAgentWorkbench(
  route = '/agent?task_id=task-test-01&investigation_id=inv_wo_dian_002',
  initialCases = []
) {
  const defaultTasksState = {
    tasks: [
      {
        id: 'task-test-01',
        status: 'completed',
        image_path: '/data/窝点嫌疑人计算机镜像.E01',
        metadata: { workflow_type: 'agent', device_scope: 'src_pc' },
      },
      {
        id: 'task-test-02',
        status: 'completed',
        image_path: '/data/服务器镜像.E01',
        metadata: { workflow_type: 'agent', device_scope: 'src_server' },
      },
    ],
    currentTask: { id: 'task-test-01' },
  };
  const defaultCasesState = { cases: initialCases };

  const store = configureStore({
    reducer: {
      tasks: (state = defaultTasksState) => state,
      cases: (state = defaultCasesState) => state,
    },
  });

  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <AgentWorkbench />
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  service.getAgentState.mockResolvedValue(mockAgentState);
  service.getAgentTrajectory.mockResolvedValue({
    task_id: 'task-test-01',
    investigation_id: 'inv_wo_dian_002',
    total: 2,
    events: mockTrajectoryEvents,
  });
  service.listAgentReviewCandidates.mockResolvedValue(mockCandidates);
  service.getAgentReviewCandidate.mockImplementation((taskId, candId) => {
    const found = mockCandidates.find((c) => c.candidate_id === candId);
    return Promise.resolve(found || mockCandidates[0]);
  });
  service.getAgentReviewHistory.mockResolvedValue([]);
  service.submitAgentReviewDecision.mockResolvedValue({
    decision: 'accepted',
    reviewed_at: '2026-10-18T12:00:00Z',
    reviewer: 'lead_forensic_analyst',
    note: 'Approved by analyst',
  });
  service.executeAgentCycle.mockResolvedValue({
    starting_revision: 2,
    ending_revision: 3,
    status: 'completed',
  });
});

test('R1: AgentWorkbench renders header, mission, status badge, and revision', async () => {
  renderAgentWorkbench();

  expect(await screen.findByText('TraceLens Agent v0 智能研判中心')).toBeInTheDocument();
  expect(screen.getByTestId('agent-execution-status-badge')).toHaveTextContent(/idle/);
  expect(screen.getByTestId('agent-state-revision')).toHaveTextContent('Rev 2');
  expect(screen.getByText(/案件目标：/)).toBeInTheDocument();
});

test('R2: Left column renders 7 investigation pillars and supports trajectory tab switch', async () => {
  renderAgentWorkbench();

  expect(await screen.findByText('诈骗话术体系与培训资料库')).toBeInTheDocument();
  expect(screen.getByText('涉案嫌疑人身份与层级架构')).toBeInTheDocument();

  // Switch to execution trajectory tab
  fireEvent.click(screen.getByRole('button', { name: '执行轨迹' }));
  expect(screen.getAllByText(/Supervisor 目标制定/)[0]).toBeInTheDocument();
  expect(screen.getAllByText(/GroundingValidator 接地校验/)[0]).toBeInTheDocument();
});

test('R3: Middle column renders metric counters and candidate items', async () => {
  renderAgentWorkbench();

  expect(await screen.findByTestId('candidate-item-f-pillar1-scripts-01')).toBeInTheDocument();
  expect(screen.getByTestId('candidate-item-h-pillar6-cryptocoin-01')).toBeInTheDocument();
  expect(screen.getByText('100%')).toBeInTheDocument(); // Grounding rate
});

test('R4: Candidate details display full statement, provenance button, and hypothesis warning', async () => {
  renderAgentWorkbench();

  await waitFor(() => {
    expect(screen.getByTestId('candidate-item-h-pillar6-cryptocoin-01')).toBeInTheDocument();
  });

  // Click on hypothesis candidate
  fireEvent.click(screen.getByTestId('candidate-item-h-pillar6-cryptocoin-01'));

  await waitFor(() => {
    expect(screen.getByTestId('hypothesis-epistemic-warning')).toBeInTheDocument();
  });
  expect(screen.getByTestId('candidate-full-content')).toHaveTextContent(
    '涉案人员使用 TrueCrypt 卷与境外 ETH 钱包进行赃款规避洗钱'
  );
  expect(screen.getByTestId('evidence-ref-file:/TrueCrypt/volume.tc')).toBeInTheDocument();
});

test('R5: Analyst review workflow allows accepting a pending candidate with note', async () => {
  renderAgentWorkbench();

  // Select pending candidate
  await waitFor(() => {
    expect(screen.getByTestId('candidate-item-h-pillar6-cryptocoin-01')).toBeInTheDocument();
  });
  fireEvent.click(screen.getByTestId('candidate-item-h-pillar6-cryptocoin-01'));

  // Open review confirmation dialog
  const acceptBtn = await screen.findByTestId('btn-accept-candidate');
  fireEvent.click(acceptBtn);

  expect(screen.getByTestId('review-confirmation-dialog')).toBeInTheDocument();

  // Input analyst note
  const noteInput = screen.getByTestId('review-note-input');
  fireEvent.change(noteInput, { target: { value: 'Confirmed ETH wallet artifact on disk' } });

  // Submit review
  const confirmBtn = screen.getByTestId('btn-confirm-review-action');
  fireEvent.click(confirmBtn);

  await waitFor(() => {
    expect(service.submitAgentReviewDecision).toHaveBeenCalledWith(
      expect.objectContaining({
        decision: 'accepted',
        note: 'Confirmed ETH wallet artifact on disk',
        review_target_id: 'h-pillar6-cryptocoin-01',
      })
    );
  });
});

test('R6: Start Agent Cycle button triggers executeAgentCycle', async () => {
  renderAgentWorkbench();

  const cycleBtn = await screen.findByTestId('btn-start-agent-cycle');
  fireEvent.click(cycleBtn);

  await waitFor(() => {
    expect(service.executeAgentCycle).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: 'task-test-01',
        max_steps: 5,
      }),
      'task-test-01'
    );
  });
});

test('R7: Single-image mode renders single-image badge and current image info', async () => {
  renderAgentWorkbench('/agent?task_id=task-test-01');

  expect(await screen.findByTestId('mode-badge-single-image')).toBeInTheDocument();
  expect(screen.getByText('🖥️ 单镜像独立调查模式')).toBeInTheDocument();
  expect(screen.getByText('窝点嫌疑人计算机镜像.E01')).toBeInTheDocument();
  expect(screen.queryByTestId('case-member-matrix')).not.toBeInTheDocument();
});

test('R8: Cross-image mode renders cross-image badge, member matrix, and device badges on candidates', async () => {
  const mockCase = {
    id: 'case-01',
    name: '杀猪盘团伙专案',
    task_ids: ['task-test-01', 'task-test-02'],
  };

  renderAgentWorkbench('/agent?task_id=task-test-01&case_id=case-01', [mockCase]);

  // Mode badge
  expect(await screen.findByTestId('mode-badge-cross-image')).toBeInTheDocument();
  expect(screen.getByText(/跨镜像多设备联合研判模式/)).toBeInTheDocument();
  expect(screen.getByText('杀猪盘团伙专案')).toBeInTheDocument();

  // Member matrix
  expect(screen.getByTestId('case-member-matrix')).toBeInTheDocument();
  expect(screen.getByTestId('case-member-card-task-test-01')).toBeInTheDocument();
  expect(screen.getByTestId('case-member-card-task-test-02')).toBeInTheDocument();

  // Device Filter Group
  expect(screen.getByTestId('filter-device-group')).toBeInTheDocument();

  // Candidate badges
  expect(await screen.findByTestId('badge-scope-f-pillar1-scripts-01')).toHaveTextContent(/嫌疑人计算机/);
});

test('R9: In cross-image mode, focusing a device displays the cancel focus buttons', async () => {
  const mockCase = {
    id: 'case-01',
    name: '杀猪盘团伙专案',
    task_ids: ['task-test-01', 'task-test-02'],
  };

  renderAgentWorkbench('/agent?task_id=task-test-01&case_id=case-01', [mockCase]);

  expect(await screen.findByTestId('mode-badge-cross-image')).toBeInTheDocument();
  expect(screen.getByTestId('btn-cancel-device-focus-header')).toBeInTheDocument();
  expect(screen.getByTestId('btn-cancel-device-focus-matrix')).toBeInTheDocument();
  expect(screen.getByTestId('btn-cancel-focus-task-test-01')).toBeInTheDocument();
  expect(screen.getByText('聚焦中')).toBeInTheDocument();
});

test('R10: All-devices global view displays global overview card as active and hides cancel focus buttons', async () => {
  const mockCase = {
    id: 'case-01',
    name: '杀猪盘团伙专案',
    task_ids: ['task-test-01', 'task-test-02'],
  };

  renderAgentWorkbench('/agent?case_id=case-01', [mockCase]);

  expect(await screen.findByTestId('mode-badge-cross-image')).toBeInTheDocument();
  expect(screen.getByTestId('case-member-card-all')).toBeInTheDocument();
  expect(screen.getByText('当前全景')).toBeInTheDocument();
  expect(screen.queryByTestId('btn-cancel-device-focus-matrix')).not.toBeInTheDocument();
  expect(screen.queryByTestId('btn-cancel-device-focus-header')).not.toBeInTheDocument();
});

test('R11: Member matrix collapse toggle allows toggling between expanded grid and compact ribbon', async () => {
  const mockCase = {
    id: 'case-01',
    name: '杀猪盘团伙专案',
    task_ids: ['task-test-01', 'task-test-02'],
  };

  renderAgentWorkbench('/agent?case_id=case-01', [mockCase]);

  expect(await screen.findByTestId('btn-toggle-matrix-collapse')).toHaveTextContent('收起');

  // Click collapse button
  fireEvent.click(screen.getByTestId('btn-toggle-matrix-collapse'));
  expect(screen.getByTestId('btn-toggle-matrix-collapse')).toHaveTextContent('展开');

  // Both cards are still accessible in collapsed ribbon
  expect(screen.getByTestId('case-member-card-all')).toBeInTheDocument();
  expect(screen.getByTestId('case-member-card-task-test-01')).toBeInTheDocument();

  // Click expand button to restore
  fireEvent.click(screen.getByTestId('btn-toggle-matrix-collapse'));
  expect(screen.getByTestId('btn-toggle-matrix-collapse')).toHaveTextContent('收起');
});
