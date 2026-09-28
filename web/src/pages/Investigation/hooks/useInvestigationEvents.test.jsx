import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import useInvestigationEvents from './useInvestigationEvents';
import * as service from '../../../services/investigationService';
vi.mock('../../../services/investigationService', () => ({
  getOverview: vi.fn(), bootstrapInvestigation: vi.fn(), getInvestigationEvents: vi.fn(),
}));
describe('historical empty store browsing', () => {
  it('does not bootstrap a readonly empty v7 investigation', async () => {
    service.getOverview.mockResolvedValue({ initialized: false, read_only: true, store_schema_version: 7 });
    service.getInvestigationEvents.mockResolvedValue({ events: [] });
    const { result } = renderHook(() => useInvestigationEvents('synthetic-v7'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.overview.read_only).toBe(true);
    expect(service.bootstrapInvestigation).not.toHaveBeenCalled();
  });
});
