import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';
import PeopleGraphPanel from './PeopleGraphPanel';
import { peopleStyle } from './peopleGraphStyles';
import { peopleGraphFixture, peopleDetailFixture, peopleRun, peopleRunId } from '../../test/fixtures/peopleGraph';

function Canvas({ nodes, links, selectedId, onNode, onLink }) {
  return <div data-testid="synthetic-canvas">{nodes.map(n => <button type="button" key={n.id}
    data-testid={`canvas-node-${n.id}`} data-selected={selectedId === n.id} style={{ color: peopleStyle(n.assessment).color }}
    onClick={() => onNode(n)}>{n.name}</button>)}{links.map(l => <button type="button" key={l.id} onClick={() => onLink(l)}>关系 {l.label}</button>)}</div>;
}
const taskLoader = vi.fn().mockResolvedValue({ case_description: '保存的案情' });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
function setup(extra = {}) {
  const service = {
    listPeopleRuns: vi.fn().mockResolvedValue({ runs: [peopleRun()] }),
    getPeopleGraph: vi.fn().mockImplementation(async (task, id, f) => peopleGraphFixture(f, id, task)),
    getPeopleTarget: vi.fn().mockImplementation(async (_task, _run, id) => peopleDetailFixture(id)),
    startPeopleRun: vi.fn().mockResolvedValue(peopleRun('pg_' + '2'.repeat(32), 'running')),
    getPeopleRun: vi.fn().mockResolvedValue(peopleRun()),
    reviewPeopleIdentity: vi.fn().mockResolvedValue(peopleRun('pg_' + '3'.repeat(32))),
    cancelPeopleRun: vi.fn(),
  };
  const props = { taskId: 'T', service, taskLoader, Canvas, pollMs: 10, ...extra };
  return { service, props, ...render(<MemoryRouter><PeopleGraphPanel {...props} /></MemoryRouter>) };
}

describe('people graph UI', () => {
  test('reads stored versions without automatically extracting or scoring', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    expect(service.startPeopleRun).not.toHaveBeenCalled();
    expect(screen.getByTestId('people-coverage')).toHaveTextContent('人员候选 4');
    expect(screen.getByTestId('canvas-node-p1')).toHaveStyle({ color: '#7C3AED' });
    expect(screen.getByTestId('canvas-node-p3')).toBeInTheDocument();
  });

  test('core filter and optional context use server queries before rendering', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    fireEvent.change(screen.getByLabelText('图谱优先级'), { target: { value: 'core' } });
    await waitFor(() => expect(screen.queryByTestId('canvas-node-p2')).toBeNull());
    await screen.findByTestId('canvas-node-p1');
    fireEvent.click(screen.getByLabelText(/显示一层上下文/));
    await screen.findByTestId('canvas-node-p2');
    expect(service.getPeopleGraph).toHaveBeenLastCalledWith('T', peopleRunId, expect.objectContaining({ priority: 'core', include_context: true }));
    expect(screen.getByTestId('canvas-node-p1')).toHaveStyle({ color: '#7C3AED' });
  });

  test('search controls stay mounted while a changed filter is loading', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    const slow = deferred();
    service.getPeopleGraph.mockReturnValueOnce(slow.promise);
    const input = screen.getByLabelText('图谱名称搜索');
    input.focus();
    fireEvent.change(input, { target: { value: '张' } });
    expect(screen.getByLabelText('图谱名称搜索')).toBe(input);
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: '张三' } });
    await screen.findByTestId('people-list');
    await act(async () => slow.resolve(peopleGraphFixture()));
    expect(screen.getByLabelText('图谱名称搜索')).toHaveValue('张三');
    expect(screen.queryByTestId('canvas-node-p3')).toBeNull();
  });

  test('source drawer preserves literal text and exact task/run/target identity', async () => {
    const { service } = setup();
    fireEvent.click(await screen.findByTestId('canvas-node-p1'));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText(/<img src=x/);
    expect(dialog.querySelector('img')).toBeNull();
    expect(service.getPeopleTarget).toHaveBeenCalledWith('T', peopleRunId, 'p1');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('view focus changes only filtering, never core priority or model execution', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    fireEvent.click(screen.getAllByText('设为查看中心')[1]);
    await waitFor(() => expect(service.getPeopleGraph).toHaveBeenLastCalledWith('T', peopleRunId, expect.objectContaining({ focus_id: 'p2' })));
    await screen.findByTestId('canvas-node-p1');
    expect(screen.getByTestId('canvas-node-p1')).toHaveStyle({ color: '#7C3AED' });
    expect(service.startPeopleRun).not.toHaveBeenCalled();
  });

  test('discovery and reassessment send explicit context and baseline without changing the task', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    fireEvent.change(screen.getByLabelText('图谱分析人'), { target: { value: '分析员' } });
    fireEvent.change(screen.getByLabelText('图谱评估案情'), { target: { value: '本轮新案情' } });
    fireEvent.click(screen.getByTestId('assess-people'));
    await waitFor(() => expect(service.startPeopleRun).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'assess', task_id: 'T', base_run_id: peopleRunId, case_description: '本轮新案情', requested_by: '分析员',
    })));
  });

  test('late saved task context does not overwrite an edit', async () => {
    const slow = deferred();
    setup({ taskLoader: vi.fn().mockReturnValue(slow.promise) });
    fireEvent.change(screen.getByLabelText('图谱评估案情'), { target: { value: '正在编辑' } });
    await act(async () => slow.resolve({ case_description: '旧案情' }));
    expect(screen.getByLabelText('图谱评估案情')).toHaveValue('正在编辑');
  });

  test('late task graph response is discarded on a scope change', async () => {
    const { service, rerender, props } = setup();
    await screen.findByTestId('people-list');
    const slow = deferred();
    service.getPeopleGraph.mockReturnValueOnce(slow.promise);
    fireEvent.change(screen.getByLabelText('图谱优先级'), { target: { value: 'P1' } });
    service.listPeopleRuns.mockResolvedValue({ runs: [] });
    rerender(<MemoryRouter><PeopleGraphPanel {...props} taskId="U" /></MemoryRouter>);
    await act(async () => slow.resolve(peopleGraphFixture()));
    expect(screen.queryByTestId('people-list')).toBeNull();
  });

  test('identity merge requires actor/reason and sends exact selected candidates', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    fireEvent.click(screen.getByLabelText('选择人员 张三'));
    fireEvent.click(screen.getByLabelText('选择人员 张三（待区分）'));
    const merge = screen.getByRole('button', { name: '将所选候选归组为一人', hidden: true });
    expect(merge).toBeDisabled();
    fireEvent.change(screen.getByLabelText('图谱分析人'), { target: { value: '复核员' } });
    fireEvent.change(screen.getByLabelText('身份调整依据'), { target: { value: '已核对身份材料' } });
    fireEvent.click(merge);
    await waitFor(() => expect(service.reviewPeopleIdentity).toHaveBeenCalledWith('T', peopleRunId, expect.objectContaining({
      operation: 'merge', person_ids: ['p1', 'p4'], reason: '已核对身份材料', reviewer: '复核员',
    })));
  });

  test('a split uses selected mention IDs and never erases the baseline', async () => {
    const { service } = setup();
    await screen.findByTestId('people-list');
    fireEvent.change(screen.getByLabelText('图谱分析人'), { target: { value: '复核员' } });
    fireEvent.click(screen.getByTestId('canvas-node-p1'));
    await screen.findByLabelText('拆分提及 m01');
    fireEvent.click(screen.getByLabelText('拆分提及 m01'));
    fireEvent.change(screen.getByLabelText('拆分依据'), { target: { value: '需要分别核查' } });
    fireEvent.click(screen.getByRole('button', { name: '将所选提及拆为另一人员候选' }));
    await waitFor(() => expect(service.reviewPeopleIdentity).toHaveBeenCalledWith('T', peopleRunId, expect.objectContaining({
      operation: 'split', person_ids: ['p1'], mention_ids: ['m01'], reason: '需要分别核查',
    })));
  });
});
