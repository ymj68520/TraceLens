import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import InvestigationTimeline from './InvestigationTimeline';

const T0 = 1_700_000_000;

const mk = (id, start, extra = {}) => ({
  id,
  start_time: start,
  end_time: start === null ? null : start + 60,
  title: `事件 ${id}`,
  summary: `${id} 的摘要内容`,
  review_status: 'draft',
  evidence_counts: { primary: 2, supporting: 1, contradicting: 0 },
  report_evidence_count: 3,
  source: 'cluster_seed',
  ...extra,
});

const fmt = (unix) => new Date(unix * 1000).toLocaleString('zh-CN');

test('轴体两端显示证据最早/最晚时间，节点按时间升序左右交替', () => {
  const events = [mk('b', T0 + 600), mk('a', T0), mk('c', T0 + 1200)];
  render(<InvestigationTimeline events={events} selectedEventId={null} onSelect={vi.fn()} loading={false} />);

  expect(screen.getByTestId('timeline-axis-start')).toHaveTextContent(fmt(T0));
  expect(screen.getByTestId('timeline-axis-end')).toHaveTextContent(fmt(T0 + 1260));
  expect(screen.getByTestId('timeline-axis-end')).toHaveTextContent(fmt(T0 + 1260));

  // 排序：最早的事件在轴顶（DOM 靠前）
  const chips = screen.getAllByTestId(/^event-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['event-chip-a', 'event-chip-b', 'event-chip-c']);

  // 左右交替挂点
  const sides = screen.getAllByTestId(/^event-/).filter((el) => el.dataset.side).map((el) => el.dataset.side);
  expect(sides).toEqual(['left', 'right', 'left']);
});

test('点击节点才展开卡片，再点收起；每次点击同步 onSelect', () => {
  const onSelect = vi.fn();
  const events = [mk('a', T0), mk('b', T0 + 600)];
  render(<InvestigationTimeline events={events} selectedEventId={null} onSelect={onSelect} loading={false} />);

  // 初始全部收起：没有卡片
  expect(screen.queryByTestId('event-card-a')).not.toBeInTheDocument();

  const nodeA = screen.getByTestId('event-node-a');
  expect(nodeA).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(nodeA);

  expect(screen.getByTestId('event-card-a')).toBeInTheDocument();
  expect(screen.getByTestId('event-card-a')).toHaveTextContent('事件 a');
  expect(screen.getByTestId('event-card-a')).toHaveTextContent('a 的摘要内容');
  expect(nodeA).toHaveAttribute('aria-expanded', 'true');
  expect(onSelect).toHaveBeenCalledWith('a');

  // 展开时该侧的折叠标签隐藏，避免与卡片重复
  expect(screen.queryByTestId('event-chip-a')).not.toBeInTheDocument();

  // 展开另一个时，旧卡片收起（同时只展开一张）
  fireEvent.click(screen.getByTestId('event-node-b'));
  expect(screen.getByTestId('event-card-b')).toBeInTheDocument();
  expect(screen.queryByTestId('event-card-a')).not.toBeInTheDocument();

  // 再点自己：收起
  fireEvent.click(screen.getByTestId('event-node-b'));
  expect(screen.queryByTestId('event-card-b')).not.toBeInTheDocument();
  expect(screen.getByTestId('event-node-b')).toHaveAttribute('aria-expanded', 'false');
  expect(onSelect).toHaveBeenCalledTimes(3);
});

test('节点圆点颜色随 review_status 变化，选中节点带 aria-current', () => {
  const events = [
    mk('a', T0, { review_status: 'confirmed' }),
    mk('b', T0 + 600, { review_status: 'rejected' }),
  ];
  render(<InvestigationTimeline events={events} selectedEventId="a" onSelect={vi.fn()} loading={false} />);

  expect(screen.getByTestId('event-node-a').className).toContain('bg-emerald-500');
  expect(screen.getByTestId('event-node-b').className).toContain('bg-rose-500');
  expect(screen.getByTestId('event-node-a')).toHaveAttribute('aria-current', 'true');
});

test('无时间的事件垫底并显示 时间未知', () => {
  const events = [mk('x', null), mk('a', T0), mk('y', 'junk')];
  render(<InvestigationTimeline events={events} selectedEventId={null} onSelect={vi.fn()} loading={false} />);

  const chips = screen.getAllByTestId(/^event-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['event-chip-a', 'event-chip-x', 'event-chip-y']);
  // 两条无时间节点 + 轴体两端均为可解析时间：恰好 2 处 时间未知
  expect(screen.getAllByText('时间未知')).toHaveLength(2);
  expect(screen.getByTestId('timeline-axis-start')).toHaveTextContent(fmt(T0));
});

test('空列表与加载态保持原语义', () => {
  const { container, rerender } = render(<InvestigationTimeline events={[]} selectedEventId={null} onSelect={vi.fn()} loading={false} />);
  expect(screen.getByText(/暂无调查事件/)).toBeInTheDocument();

  rerender(<InvestigationTimeline events={[]} selectedEventId={null} onSelect={vi.fn()} loading />);
  expect(container.querySelector('.animate-spin')).not.toBeNull();
});
