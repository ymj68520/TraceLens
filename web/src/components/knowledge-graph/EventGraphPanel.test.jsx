import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import EventGraphPanel from './EventGraphPanel';
import CommunicationGraphEntry from './CommunicationGraphEntry';
import { eventDetailFixture, eventGraphFixture, eventPeopleId, eventRun, eventRunId } from '../../test/fixtures/eventGraph';

vi.mock('./EventGraphCanvas', () => ({ default: ({ nodes, onSelect }) => <div data-testid="event-graph-canvas">{nodes.map(n => <button key={n.id} onClick={() => onSelect(n.id)}>{n.name}</button>)}</div> }));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function setup(extra = {}) {
  const service = {
    listEventRuns: vi.fn().mockResolvedValue({ runs: [eventRun()] }),
    getEventView: vi.fn().mockImplementation(async (_task, filters) => eventGraphFixture(filters)),
    getEventRunGraph: vi.fn().mockImplementation(async (_task, run, filters) => eventGraphFixture(filters, run)),
    getEventDetail: vi.fn().mockImplementation(async (_task, id) => eventDetailFixture(id)),
    getEventRunDetail: vi.fn().mockImplementation(async (_task, run, id) => eventDetailFixture(id, run)),
    startEventRun: vi.fn().mockResolvedValue(eventRun('pg_' + 'b'.repeat(32), 'running')),
    getEventRun: vi.fn().mockImplementation(async (_task, id) => eventRun(id)),
    cancelEventRun: vi.fn().mockImplementation(async (_task, id) => eventRun(id, 'cancelled')),
  };
  const props = { taskId: 'T', view: 'events', service, peopleLoader: vi.fn().mockResolvedValue({ runs: [eventRun(eventPeopleId)] }), pollMs: 10, ...extra };
  const result = render(<MemoryRouter><EventGraphPanel {...props} /></MemoryRouter>);
  return { service, props, ...result };
}

describe('event graph UI', () => {
  test('reads existing data without model submission and traces exact source version', async () => {
    const { service } = setup();
    await screen.findByRole('button', { name: '孤立事件' });
    expect(service.startEventRun).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '付款安排' }));
    await screen.findByText(/初次分析摘要；尚未核对原文/);
    expect(service.getEventDetail).toHaveBeenCalledWith('T', 'event:e1', 'f'.repeat(64));
    expect(screen.getByText('准确版本：v2')).toBeInTheDocument();
  });

  test('explicit analysis binds selected people version then polls a new run', async () => {
    const { service } = setup();
    await screen.findByRole('button', { name: '孤立事件' });
    await waitFor(() => expect(screen.getByLabelText('关联人员版本').options).toHaveLength(2));
    fireEvent.change(screen.getByLabelText('事件分析人'), { target: { value: '分析员' } });
    fireEvent.change(screen.getByLabelText('关联人员版本'), { target: { value: eventPeopleId } });
    fireEvent.click(screen.getByRole('button', { name: '生成智能关联新版本' }));
    await waitFor(() => expect(service.startEventRun).toHaveBeenCalledWith(expect.objectContaining({ task_id: 'T', people_run_id: eventPeopleId, event_ids: [], requested_by: '分析员' })));
    await waitFor(() => expect(service.getEventRunGraph).toHaveBeenCalled());
    expect(screen.getByLabelText('事件图谱版本').value).toBe('pg_' + 'b'.repeat(32));
  });

  test('historical selection is preserved when a later submission returns', async () => {
    const { service } = setup();
    await screen.findByRole('button', { name: '孤立事件' });
    const late = deferred(); service.startEventRun.mockReturnValueOnce(late.promise);
    fireEvent.change(screen.getByLabelText('事件分析人'), { target: { value: '分析员' } });
    fireEvent.click(screen.getByRole('button', { name: '生成智能关联新版本' }));
    fireEvent.change(screen.getByLabelText('事件图谱版本'), { target: { value: eventRunId } });
    await act(async () => late.resolve(eventRun('pg_' + 'c'.repeat(32), 'running')));
    expect(screen.getByLabelText('事件图谱版本').value).toBe(eventRunId);
  });

  test('search keeps focus and ignores late responses', async () => {
    const { service } = setup();
    await screen.findByRole('button', { name: '孤立事件' });
    const late = deferred(); service.getEventView.mockReturnValueOnce(late.promise);
    const input = screen.getByLabelText('事件图谱搜索'); input.focus();
    fireEvent.change(input, { target: { value: '付款' } });
    fireEvent.change(input, { target: { value: '孤立' } });
    await screen.findByRole('button', { name: '孤立事件' });
    await act(async () => late.resolve(eventGraphFixture({ query: '付款' })));
    expect(screen.queryByRole('button', { name: '付款安排' })).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  test('late trace does not reopen closed detail', async () => {
    const { service } = setup();
    await screen.findByRole('button', { name: '付款安排' });
    const late = deferred(); service.getEventDetail.mockReturnValueOnce(late.promise);
    fireEvent.click(screen.getByRole('button', { name: '付款安排' }));
    fireEvent.click(screen.getByRole('button', { name: '关闭详情' }));
    await act(async () => late.resolve(eventDetailFixture('event:e1')));
    expect(screen.queryByTestId('event-source-detail')).toBeNull();
  });

  test('switching views retains history and shows source changes and coverage', async () => {
    const { props, service, rerender } = setup({ initialRunId: eventRunId });
    await screen.findByRole('button', { name: '孤立事件' });
    service.getEventRunGraph.mockImplementation(async (_task, run, filters) => ({ ...eventGraphFixture(filters, run), freshness: { investigation: 'changed' } }));
    rerender(<MemoryRouter><EventGraphPanel {...props} view="associations" /></MemoryRouter>);
    await screen.findByRole('button', { name: '张三' });
    expect(screen.getByLabelText('事件图谱版本').value).toBe(eventRunId);
    expect(screen.getByText(/当前来源或人员版本已有变化/)).toBeInTheDocument();
    expect(screen.getByText(/没有生成建议不等于没有关联/)).toBeInTheDocument();
    expect(service.startEventRun).not.toHaveBeenCalled();
  });

  test('a remounted task cannot receive the previous tasks delayed data', async () => {
    const { service, props, rerender } = setup();
    await screen.findByRole('button', { name: '付款安排' });
    const late = deferred(); service.getEventView.mockReturnValueOnce(late.promise);
    fireEvent.change(screen.getByLabelText('事件图谱搜索'), { target: { value: '付款' } });
    service.getEventView.mockResolvedValue({ ...eventGraphFixture(), nodes: [], links: [], items: [], total_items: 0 });
    rerender(<MemoryRouter><EventGraphPanel {...props} key="U" taskId="U" /></MemoryRouter>);
    await act(async () => late.resolve(eventGraphFixture()));
    await waitFor(() => expect(screen.queryByRole('button', { name: '付款安排' })).toBeNull());
  });
});

test('communications links distinguish task context from account imports', () => {
  render(<MemoryRouter><CommunicationGraphEntry taskId="T/中文" /></MemoryRouter>);
  expect(screen.getByRole('link', { name: '查看当前任务通讯关系' })).toHaveAttribute('href', '/im-forensics?tab=graph&task_id=T%2F%E4%B8%AD%E6%96%87');
  expect(screen.getByRole('link', { name: '选择 QQ 导入记录' })).toHaveAttribute('href', '/im-forensics?platform=qq&tab=graph');
});
