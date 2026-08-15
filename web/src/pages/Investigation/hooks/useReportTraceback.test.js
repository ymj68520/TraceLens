import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import useReportTraceback from './useReportTraceback';
import { getClaimProvenance } from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({
  getClaimProvenance: vi.fn(),
}));

function deferred() {
  let resolve;
  const promise = new Promise((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

const report = {
  citation_manifest: [
    { citation_id: 'CIT-001', evidence_key: 'file:/a', evidence_type: 'file' },
  ],
  claim_manifest: [
    { claim_id: 'claim-1', citation_ids: ['CIT-001'] },
  ],
};

beforeEach(() => vi.clearAllMocks());

test('opens citation locally without requesting claim provenance', () => {
  const { result } = renderHook(() => useReportTraceback('task-a', 'report-1', report));

  act(() => result.current.openCitation('CIT-001'));

  expect(result.current.selectedTrace).toEqual({ type: 'citation', id: 'CIT-001' });
  expect(result.current.citationTrace.evidence_key).toBe('file:/a');
  expect(getClaimProvenance).not.toHaveBeenCalled();
});

test('clears trace when report identity changes', async () => {
  const { result, rerender } = renderHook(
    ({ taskId, reportId }) => useReportTraceback(taskId, reportId, report),
    { initialProps: { taskId: 'task-a', reportId: 'report-1' } },
  );

  act(() => result.current.openCitation('CIT-001'));
  rerender({ taskId: 'task-a', reportId: 'report-2' });

  await waitFor(() => expect(result.current.selectedTrace).toBeNull());
});

test('ignores late Claim response after a newer Claim selection', async () => {
  const first = deferred();
  const second = deferred();
  getClaimProvenance.mockImplementation((taskId, claimId) => claimId === 'claim-a' ? first.promise : second.promise);
  const { result } = renderHook(() => useReportTraceback('task-a', 'report-1', report));

  act(() => { void result.current.openClaim('claim-a'); });
  act(() => { void result.current.openClaim('claim-b'); });
  await waitFor(() => expect(getClaimProvenance).toHaveBeenCalledWith('task-a', 'claim-b'));

  await act(async () => {
    first.resolve({ claim: { claim_id: 'claim-a' } });
    second.resolve({ claim: { claim_id: 'claim-b' } });
  });

  await waitFor(() => expect(result.current.claimDetail?.claim_id).toBe('claim-b'));
});
