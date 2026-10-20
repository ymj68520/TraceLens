import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import TimelineSummaryPanel from './TimelineSummaryPanel';
import { timelineSummaryFixture, timelineRecordsFixture } from '../../test/fixtures/timelineSummary';

const endpoint = '/api/associations/timeline-summary';
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const setup = (props = {}) => {
  const data = timelineSummaryFixture();
  const loadSummary = vi.fn().mockResolvedValue(data);
  const loadRecords = vi.fn().mockResolvedValue(timelineRecordsFixture(data.context));
  const args = { endpoint, scopeParams: { task_id: 'T', source: 'events' }, loadSummary, loadRecords, ...props };
  return { ...render(<TimelineSummaryPanel {...args} />), loadSummary, loadRecords, args, data };
};
const generate = async () => {
  fireEvent.click(screen.getByTestId('timeline-summary-generate'));
  await screen.findByTestId('timeline-summary-result');
};

describe('timeline summary', () => {
  test('runs only on demand and retains existing task/time/type filters', async () => {
    const { loadSummary } = setup({ scopeParams: { task_id: 'T', source: 'events', start_time: 1, end_time: 9, event_type: 'CREATED' } });
    expect(loadSummary).not.toHaveBeenCalled();
    await generate();
    expect(loadSummary).toHaveBeenCalledWith(endpoint, {
      task_id: 'T', source: 'events', start_time: 1, end_time: 9, event_type: 'CREATED', timezone: 'Asia/Shanghai',
    });
    expect(screen.getByTestId('timeline-quality')).toHaveTextContent('时间缺失 1');
    expect(screen.getByText('timeline-summary:v1')).toBeInTheDocument();
    expect(screen.getByText(/本轮统计标识/)).toBeInTheDocument();
  });

  test('shows independent days, gaps, directions and explicit truncated coverage', async () => {
    setup({ communication: true, loadSummary: vi.fn().mockResolvedValue(timelineSummaryFixture({ truncated: true })) });
    await generate();
    expect(screen.getByText(/3\/3 个有记录日期/)).toBeInTheDocument();
    expect(screen.getAllByText('前一日未见记录，覆盖未知')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /收到 1 条/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /方向未知 1 条/ })).toBeInTheDocument();
    expect(screen.getByTestId('timeline-truncation')).toHaveTextContent('未扫描 100 条');
  });

  test('record drilldown carries exact source and query version and escapes body', async () => {
    const { loadRecords, data } = setup();
    await generate();
    fireEvent.click(screen.getByRole('button', { name: '22时：6条，3个日期' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText(/message:1/);
    expect(loadRecords).toHaveBeenCalledWith(endpoint, expect.objectContaining({
      task_id: 'T', hour: 22, source_version: data.context.source_version,
      summary_id: data.context.context_id, offset: 0, limit: 50,
    }));
    expect(within(dialog).getByText(/<img src=x/)).toBeInTheDocument();
    expect(dialog.querySelector('img')).toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('a source revision conflict blocks old drilldown until regenerated', async () => {
    const { loadRecords } = setup();
    loadRecords.mockRejectedValueOnce({ status: 409, data: { detail: '来源已更新' } });
    await generate();
    fireEvent.click(screen.getByRole('button', { name: /有效 6/ }));
    await screen.findByText('来源已更新');
    fireEvent.click(screen.getByRole('button', { name: '关闭回查' }));
    expect(screen.getByRole('button', { name: /有效 6/ })).toBeDisabled();
    await generate();
    expect(screen.getByRole('button', { name: /有效 6/ })).not.toBeDisabled();
  });

  test('timezone changes discard the old result and preserve local date filter strings', async () => {
    const { loadSummary } = setup();
    await generate();
    fireEvent.change(screen.getByLabelText('分析时区'), { target: { value: 'America/New_York' } });
    expect(screen.queryByTestId('timeline-summary-result')).toBeNull();
    fireEvent.change(screen.getByLabelText('总结开始日期'), { target: { value: '2026-11-01' } });
    await generate();
    expect(loadSummary).toHaveBeenLastCalledWith(endpoint, expect.objectContaining({ timezone: 'America/New_York', start_date: '2026-11-01' }));
  });

  test('invalid local date interval is blocked before calling the server', async () => {
    const { loadSummary } = setup();
    fireEvent.change(screen.getByLabelText('总结开始日期'), { target: { value: '2026-11-02' } });
    fireEvent.change(screen.getByLabelText('总结结束日期'), { target: { value: '2026-11-01' } });
    expect(screen.getByTestId('timeline-summary-generate')).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('开始日期不能晚于结束日期');
    expect(loadSummary).not.toHaveBeenCalled();
  });

  test('event source filtering clears a previous summary before regenerating', async () => {
    const { loadSummary } = setup();
    await generate();
    fireEvent.change(screen.getByLabelText('事件来源'), { target: { value: 'LINUX_SYSLOG' } });
    expect(screen.queryByTestId('timeline-summary-result')).toBeNull();
    await generate();
    expect(loadSummary).toHaveBeenLastCalledWith(endpoint, expect.objectContaining({ event_source: 'LINUX_SYSLOG' }));
  });

  test('late response from old task cannot populate a new task', async () => {
    const slow = deferred();
    const { rerender, args, data } = setup({ loadSummary: vi.fn().mockReturnValue(slow.promise) });
    fireEvent.click(screen.getByTestId('timeline-summary-generate'));
    rerender(<TimelineSummaryPanel {...args} scopeParams={{ task_id: 'U', source: 'events' }} />);
    await act(async () => slow.resolve(data));
    expect(screen.queryByTestId('timeline-summary-result')).toBeNull();
    expect(screen.getByText(/任务 U/)).toBeInTheDocument();
    expect(screen.getByTestId('timeline-summary-generate')).not.toBeDisabled();
  });

  test('late drilldown cannot reopen a closed drawer', async () => {
    const slow = deferred();
    const { data } = setup({ loadRecords: vi.fn().mockReturnValue(slow.promise) });
    await generate();
    fireEvent.click(screen.getByRole('button', { name: /有效 6/ }));
    fireEvent.click(screen.getByRole('button', { name: '关闭回查' }));
    await act(async () => slow.resolve(timelineRecordsFixture(data.context)));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('direction filter and record selector remain distinct and paginated', async () => {
    const { loadRecords, data } = setup({ communication: true });
    loadRecords.mockResolvedValueOnce({ ...timelineRecordsFixture(data.context), total: 51, page_truncated: true });
    fireEvent.change(screen.getByLabelText('收发方向'), { target: { value: 'sent' } });
    await generate();
    fireEvent.click(screen.getByRole('button', { name: /发出 3 条/ }));
    await screen.findByText(/符合条件 51 条/);
    fireEvent.click(screen.getByRole('button', { name: '下一页记录' }));
    await waitFor(() => expect(loadRecords).toHaveBeenLastCalledWith(endpoint,
      expect.objectContaining({ direction: 'sent', record_direction: 'sent', offset: 50 })));
  });
});
