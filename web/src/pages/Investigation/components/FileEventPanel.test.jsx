import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import FileEventPanel from './FileEventPanel';

/**
 * Regression guard for the "文件关联调查事件 0" empty column.
 *
 * The column was empty because no investigation events were seeded at all
 * (taskEventCount === 0 rendered 暂无调查事件). These cases pin the three
 * states the panel must distinguish: no file, file with events, file whose
 * task has events but none linked.
 */
describe('FileEventPanel file-centric events', () => {
  const file = {
    path: '/Windows/Prefetch/CHROME.EXE-AAA.pf',
    name: 'CHROME.EXE-AAA.pf',
    crtime: 1747728000,
    mtime: 1747728100,
    atime: 1747728200,
    ctime: 1747728300,
  };

  const event = {
    id: 'ie_1',
    title: 'CHROME.EXE-AAA.pf · 1 条工件记录',
    summary: 'Prefetch 显示 CHROME.EXE 共执行 10 次。',
    start_time: 1747729000,
    review_status: 'draft',
  };

  it('lists the events linked to the selected file and counts them', () => {
    render(
      <FileEventPanel
        file={file}
        events={[event]}
        taskEventCount={1}
        selectedEventId={null}
        onSelectEvent={() => {}}
      />
    );

    expect(screen.getByText('文件关联调查事件')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('CHROME.EXE-AAA.pf · 1 条工件记录')).toBeInTheDocument();
    expect(screen.queryByText('暂无调查事件')).not.toBeInTheDocument();
  });

  it('distinguishes "task has no events" from "this file has none"', () => {
    const { rerender } = render(
      <FileEventPanel file={file} events={[]} taskEventCount={0} onSelectEvent={() => {}} />
    );
    expect(screen.getByText('暂无调查事件')).toBeInTheDocument();

    rerender(
      <FileEventPanel file={file} events={[]} taskEventCount={7} onSelectEvent={() => {}} />
    );
    expect(screen.getByText('暂无关联事件')).toBeInTheDocument();
  });

  it('renders the fixture event time rather than an unknown marker', () => {
    render(
      <FileEventPanel file={file} events={[event]} taskEventCount={1} onSelectEvent={() => {}} />
    );
    // formatTimestamp renders a full date; the point is a real value exists.
    expect(screen.queryByText(/时间未知/)).not.toBeInTheDocument();
    expect(screen.getByTestId('file-event-ie_1')).toBeInTheDocument();
  });
});
