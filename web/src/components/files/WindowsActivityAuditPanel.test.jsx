import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import WindowsActivityAuditPanel from './WindowsActivityAuditPanel';
vi.mock('../../services/api', () => ({ default: { get: vi.fn().mockResolvedValue({ coverage: {
  complete: false, valid_records: 3, undated_records: 2, failed_records: 1,
  tables: { event_logs: { status: 'partial', input: 4, timeline_events: 3, undated: 0, failed: 1 } },
  limitations: ['恢复记录另行标识'], result_set_id: 'test-version',
} }) } }));
describe('WindowsActivityAuditPanel', () => {
  it('shows Chinese coverage and preserves uncertainty', async () => {
    render(<WindowsActivityAuditPanel taskId="task" />);
    expect(await screen.findByText(/部分可用，请核对限制/)).toBeInTheDocument();
    expect(screen.getByText(/服务和计划任务配置不等于实际执行/)).toBeInTheDocument();
    expect(screen.getByText(/事件日志：部分可用/)).toBeInTheDocument();
  });
});
