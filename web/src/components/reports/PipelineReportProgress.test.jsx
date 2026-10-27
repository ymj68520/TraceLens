import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, describe, it, expect, vi } from 'vitest';
import PipelineReportProgress from './PipelineReportProgress';
afterEach(cleanup);
describe('automatic report progress', () => {
  it('shows an upstream failure instead of telling the user to wait forever', async () => {
    render(<PipelineReportProgress taskId="T" loadTail={async () => { throw { status: 404 }; }}
      loadTask={async () => ({ status: 'failed', message: '来源索引建立失败' })} />);
    expect(await screen.findByText('报告前置处理未完成')).toBeInTheDocument();
  });
  it('shows material preparation before a generation has been admitted', async () => {
    render(<PipelineReportProgress taskId="T" loadTail={async () => ({ state: 'running' })} />);
    expect(await screen.findByText('正在准备与冻结报告材料')).toBeInTheDocument();
  });
  it('shows exact failed generation without calling it a report', async () => {
    const generation = vi.fn(async () => ({ status: 'failed', error_message: '来源校验未通过', quality: { label: '校验或执行未通过' } }));
    render(<PipelineReportProgress taskId="T" loadTail={async () => ({ state: 'running', generation_id: 'g1' })} loadGeneration={generation} />);
    expect(await screen.findByText('本轮报告生成未通过')).toBeInTheDocument();
    expect(generation).toHaveBeenCalledWith('T', 'g1');
    expect(screen.queryByText('查看本轮报告')).not.toBeInTheDocument();
  });
  it('refreshes the available report using its exact identity', async () => {
    const ready = vi.fn();
    render(<PipelineReportProgress taskId="T" loadTail={async () => ({ state: 'completed', report_id: 'r1' })} onReportAvailable={ready} />);
    expect(await screen.findByText('本轮报告已生成')).toBeInTheDocument();
    expect(ready).toHaveBeenCalledWith('r1');
  });
  it('ignores an old task response after navigation', async () => {
    let finish; const pending = new Promise(resolve => { finish = resolve; });
    const loader = vi.fn(task => task === 'old' ? pending : Promise.resolve({ state: 'running' }));
    const ready = vi.fn();
    const view = render(<PipelineReportProgress taskId="old" loadTail={loader} onReportAvailable={ready} />);
    view.rerender(<PipelineReportProgress taskId="new" loadTail={loader} onReportAvailable={ready} />);
    finish({ state: 'completed', report_id: 'old-report' });
    await waitFor(() => expect(screen.getByText('正在准备与冻结报告材料')).toBeInTheDocument());
    expect(ready).not.toHaveBeenCalled();
  });
});
