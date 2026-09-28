import { beforeEach, expect, test, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import useCitedReportVersion, { selectCitedNarrativeVersion } from './useCitedReportVersion';
import { listReportVersions } from '../../../services/reportService';

vi.mock('../../../services/reportService', () => ({ listReportVersions: vi.fn() }));

const versions = [
  { report_id: 'older', version: 1, report_kind: 'llm_generation', status: 'ready' },
  { report_id: 'snapshot', version: 4, report_kind: 'snapshot', status: 'ready' },
  { report_id: 'newer', version: 2, report_kind: 'llm_generation', status: 'ready' },
  { report_id: 'pending', version: 3, report_kind: 'llm_generation', status: 'generating' },
];

beforeEach(() => vi.clearAllMocks());

test('selects only ready narrative versions and respects an exact report id', () => {
  expect(selectCitedNarrativeVersion(versions)?.report_id).toBe('newer');
  expect(selectCitedNarrativeVersion(versions, 'older')?.report_id).toBe('older');
  expect(selectCitedNarrativeVersion(versions, 'snapshot')).toBeNull();
  expect(selectCitedNarrativeVersion([], null)).toBeNull();
});

test('loads the latest ready narrative and switches to a requested version', async () => {
  listReportVersions.mockResolvedValue(versions);
  const { result, rerender } = renderHook(
    ({ reportId }) => useCitedReportVersion('task-1', reportId),
    { initialProps: { reportId: null } },
  );
  await waitFor(() => expect(result.current.reportId).toBe('newer'));
  expect(listReportVersions).toHaveBeenCalledWith('task', 'task-1');

  rerender({ reportId: 'older' });
  await waitFor(() => expect(result.current.reportId).toBe('older'));
});

test('unknown exact report never falls back to another task file timeline', async () => {
  listReportVersions.mockResolvedValue(versions);
  const { result } = renderHook(() => useCitedReportVersion('task-1', 'foreign'));

  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.reportId).toBeNull();
  expect(result.current.error?.message).toContain('未找到');
});
