import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import ReportEvidenceJudgment from './ReportEvidenceJudgment';

vi.mock('../common/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

const mocks = vi.hoisted(() => ({
  addReportEvidence: vi.fn().mockResolvedValue({}),
  updateReportEvidenceStatus: vi.fn().mockResolvedValue({}),
}));

vi.mock('../../services/investigationService', () => ({
  addReportEvidence: mocks.addReportEvidence,
  updateReportEvidenceStatus: mocks.updateReportEvidenceStatus,
}));

beforeEach(() => {
  mocks.addReportEvidence.mockClear();
  mocks.updateReportEvidenceStatus.mockClear();
});

test('unjudged file renders judgment buttons and POSTs on first judgment', async () => {
  const onChanged = vi.fn();
  render(
    <ReportEvidenceJudgment taskId="t1" evidenceKey="file:/case/a.txt" status={null} onChanged={onChanged} />
  );

  expect(screen.getByText('未判定')).toBeInTheDocument();
  fireEvent.click(screen.getByTitle('作为报告正文证据'));
  await waitFor(() =>
    expect(mocks.addReportEvidence).toHaveBeenCalledWith('t1', 'file:/case/a.txt', 'main')
  );
  expect(mocks.updateReportEvidenceStatus).not.toHaveBeenCalled();
  await waitFor(() => expect(onChanged).toHaveBeenCalledWith('main'));
});

test('judged file switches via explicit PUT and can be excluded', async () => {
  const onChanged = vi.fn();
  render(
    <ReportEvidenceJudgment taskId="t1" evidenceKey="file:/case/a.txt" status="main" onChanged={onChanged} />
  );

  expect(screen.getByText('正文证据')).toBeInTheDocument();
  expect(screen.queryByTitle('作为报告正文证据')).not.toBeInTheDocument();
  fireEvent.click(screen.getByTitle('移出报告（保留判定痕迹）'));
  await waitFor(() =>
    expect(mocks.updateReportEvidenceStatus).toHaveBeenCalledWith('t1', 'file:/case/a.txt', 'excluded')
  );
  expect(onChanged).toHaveBeenCalledWith('excluded');
});

test('excluded file offers recovery actions instead of removal', () => {
  render(<ReportEvidenceJudgment taskId="t1" evidenceKey="file:/case/a.txt" status="excluded" />);
  expect(screen.getByText('已排除')).toBeInTheDocument();
  expect(screen.getByTitle('恢复为正文证据')).toBeInTheDocument();
  expect(screen.getByTitle('恢复为附件证据')).toBeInTheDocument();
  expect(screen.queryByTitle('移出报告（保留判定痕迹）')).not.toBeInTheDocument();
});

test('cluster evidence renders a read-only note and no judgment actions', () => {
  render(<ReportEvidenceJudgment taskId="t1" evidenceKey="cluster:v1:100:CREATED" status={null} />);
  expect(screen.getByTestId('report-judgment-cluster-note')).toBeInTheDocument();
  expect(screen.queryByTitle('作为报告正文证据')).not.toBeInTheDocument();
  expect(mocks.addReportEvidence).not.toHaveBeenCalled();
});
