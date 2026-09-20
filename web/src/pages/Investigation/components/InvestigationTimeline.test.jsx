import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import InvestigationTimeline from './InvestigationTimeline';
import { formatDatetimeLocal } from '../utils/investigationConstants';

const T0 = 1_700_000_000;

const mkEvent = (id, start, extra = {}) => ({
  id,
  start_time: start,
  end_time: start === null ? null : start + 60,
  title: `事件 ${id}`,
  review_status: 'draft',
  ...extra,
});

const mkFile = (path, latest, extra = {}) => ({
  path,
  name: path.split('/').pop(),
  size: 1024,
  latest_time: latest,
  event_ids: [],
  ...extra,
});

const fmt = (unix) => new Date(unix * 1000).toLocaleString('zh-CN');

test('节点为已分析文件，按 MACB 最新时间降序左右交替，轴端为最新时间范围', () => {
  const files = [
    mkFile('/case/b.txt', T0 + 600),
    mkFile('/case/a.txt', T0),
    mkFile('/case/c.txt', T0 + 1200),
  ];
  render(<InvestigationTimeline files={files} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);

  expect(screen.getByTestId('timeline-axis-start')).toHaveTextContent(fmt(T0));
  expect(screen.getByTestId('timeline-axis-end')).toHaveTextContent(fmt(T0 + 1200));

  // 排序：MACB 最新时间最新的文件在轴顶（DOM 靠前）
  const chips = screen.getAllByTestId(/^file-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['file-chip-/case/c.txt', 'file-chip-/case/b.txt', 'file-chip-/case/a.txt']);

  // 左右交替挂点
  const sides = screen.getAllByTestId(/^file-[^n]/).filter((el) => el.dataset.side).map((el) => el.dataset.side);
  expect(sides).toEqual(['left', 'right', 'left']);
});

test('节点以文件为核心：名称在标签上，展开卡片展示 MACB 时间与佐证事件', () => {
  const onSelectFile = vi.fn();
  const onSelectEvent = vi.fn();
  const files = [
    mkFile('/case/report.doc', T0, {
      crtime: T0 - 100,
      mtime: T0,
      atime: T0 + 10,
      ctime: T0 + 5,
      llm_summary: '文件自身的分析摘要',
      event_ids: ['e1', 'e2'],
    }),
  ];
  const events = [
    mkEvent('e1', T0 - 50),
    mkEvent('e2', T0 - 30, { review_status: 'confirmed' }),
  ];
  render(<InvestigationTimeline files={files} events={events} selectedFileKey={null} onSelectFile={onSelectFile} onSelectEvent={onSelectEvent} loading={false} />);

  expect(screen.getByText('report.doc')).toBeInTheDocument();
  expect(screen.queryByTestId('file-card-/case/report.doc')).not.toBeInTheDocument();

  const node = screen.getByTestId('file-node-/case/report.doc');
  expect(node).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(node);

  expect(onSelectFile).toHaveBeenCalledWith(expect.objectContaining({ path: '/case/report.doc' }));
  const card = screen.getByTestId('file-card-/case/report.doc');
  expect(card).toHaveTextContent('文件自身的分析摘要');
  // MACB 四类时间戳齐备
  expect(card).toHaveTextContent(`创建 ${fmt(T0 - 100)}`);
  expect(card).toHaveTextContent(`修改 ${fmt(T0)}`);
  expect(card).toHaveTextContent(`访问 ${fmt(T0 + 10)}`);
  expect(card).toHaveTextContent(`变更 ${fmt(T0 + 5)}`);
  // 佐证事件按时间升序，点击选中事件
  const eventButtons = screen.getAllByTestId(/^file-card-event-/);
  expect(eventButtons.map((el) => el.dataset.testid)).toEqual(['file-card-event-e1', 'file-card-event-e2']);
  fireEvent.click(screen.getByTestId('file-card-event-e2'));
  expect(onSelectEvent).toHaveBeenCalledWith('e2');

  // 再点节点：收起
  fireEvent.click(screen.getByTestId('file-node-/case/report.doc'));
  expect(screen.queryByTestId('file-card-/case/report.doc')).not.toBeInTheDocument();
});

test('文件圆点颜色随报告证据判定状态：正文紫、附件蓝、已排除灰、未判定琥珀', () => {
  const files = [
    mkFile('/case/a.txt', T0, { report_status: 'main' }),
    mkFile('/case/b.txt', T0 + 600, { report_status: 'appendix' }),
    mkFile('/case/c.txt', T0 + 1200, { report_status: 'excluded' }),
    mkFile('/case/d.txt', T0 + 1800),
  ];
  render(<InvestigationTimeline files={files} events={[]} selectedFileKey="/case/a.txt" onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);

  expect(screen.getByTestId('file-node-/case/a.txt').className).toContain('bg-purple-500');
  expect(screen.getByTestId('file-node-/case/b.txt').className).toContain('bg-sky-500');
  expect(screen.getByTestId('file-node-/case/c.txt').className).toContain('bg-slate-400');
  expect(screen.getByTestId('file-node-/case/d.txt').className).toContain('bg-amber-400');
  expect(screen.getByTestId('file-node-/case/a.txt')).toHaveAttribute('aria-current', 'true');
});

test('无 MACB 时间的文件垫底并显示 时间未知', () => {
  const files = [
    mkFile('/case/x.txt', null),
    mkFile('/case/a.txt', T0),
    mkFile('/case/y.txt', 'junk'),
  ];
  render(<InvestigationTimeline files={files} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);

  const chips = screen.getAllByTestId(/^file-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['file-chip-/case/a.txt', 'file-chip-/case/x.txt', 'file-chip-/case/y.txt']);
  // 两条无时间节点 + 轴体两端均为可解析时间：恰好 2 处 时间未知
  expect(screen.getAllByText('时间未知')).toHaveLength(2);
  expect(screen.getByTestId('timeline-axis-start')).toHaveTextContent(fmt(T0));
});

test('时间过滤：MACB 最新时间落在区间内的文件命中，轴端收敛，可清除', () => {
  const files = [
    mkFile('/case/a.txt', T0),
    mkFile('/case/b.txt', T0 + 600),
    mkFile('/case/c.txt', T0 + 1200),
    mkFile('/case/x.txt', null),
  ];
  render(<InvestigationTimeline files={files} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);

  // 起始时间收敛到 T0+590：命中 b、c；无时间的 x 被隐藏
  fireEvent.change(screen.getByTestId('timeline-filter-start'), { target: { value: formatDatetimeLocal(T0 + 590) } });

  let chips = screen.getAllByTestId(/^file-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['file-chip-/case/c.txt', 'file-chip-/case/b.txt']);
  expect(screen.getByTestId('timeline-filter-count')).toHaveTextContent('2/4');
  expect(screen.getByTestId('timeline-axis-start')).toHaveTextContent(fmt(T0 + 600));

  // 清除恢复全部（含无时间的 x），轴端回到全量范围
  fireEvent.click(screen.getByTestId('timeline-filter-clear'));
  chips = screen.getAllByTestId(/^file-chip-/).map((el) => el.dataset.testid);
  expect(chips).toEqual(['file-chip-/case/c.txt', 'file-chip-/case/b.txt', 'file-chip-/case/a.txt', 'file-chip-/case/x.txt']);
  expect(screen.queryByTestId('timeline-filter-count')).not.toBeInTheDocument();
  expect(screen.getByTestId('timeline-axis-end')).toHaveTextContent(fmt(T0 + 1200));
});

test('时间过滤无命中时显示空提示并隐藏轴体', () => {
  const files = [mkFile('/case/a.txt', T0)];
  render(<InvestigationTimeline files={files} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);

  fireEvent.change(screen.getByTestId('timeline-filter-end'), { target: { value: formatDatetimeLocal(T0 - 100) } });

  expect(screen.getByTestId('timeline-filter-empty')).toBeInTheDocument();
  expect(screen.queryByTestId('timeline-axis')).not.toBeInTheDocument();
});

test('空列表与加载态保持原语义', () => {
  const { container, rerender } = render(<InvestigationTimeline files={[]} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading={false} />);
  expect(screen.getByText(/暂无已分析文件/)).toBeInTheDocument();

  rerender(<InvestigationTimeline files={[]} events={[]} selectedFileKey={null} onSelectFile={vi.fn()} onSelectEvent={vi.fn()} loading />);
  expect(container.querySelector('.animate-spin')).not.toBeNull();
});
