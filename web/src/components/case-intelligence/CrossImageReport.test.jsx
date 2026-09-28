import { expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import CrossImageReport from './CrossImageReport';

test('renders a persisted cross-image report without changing its text', async () => {
  const loadReport = vi.fn().mockResolvedValue({ report: '# Findings\nExisting evidence only.', generated_at: '2026-09-23' });
  render(<CrossImageReport caseId="case-1" loadReport={loadReport} />);

  expect(await screen.findByText('跨镜像研判报告')).toBeInTheDocument();
  expect(screen.getByText(/Existing evidence only/)).toBeInTheDocument();
  expect(loadReport).toHaveBeenCalledWith('case-1');
});

test('shows an actionable missing-report warning for historical 404s', async () => {
  const loadReport = vi.fn().mockRejectedValue({ status: 404 });
  render(<CrossImageReport caseId="case-2" loadReport={loadReport} />);

  expect(await screen.findByRole('alert')).toHaveTextContent('跨镜像报告缺失');
  expect(screen.getByRole('button', { name: '重试读取' })).toBeInTheDocument();
});

test('does not mislabel a server failure as missing historical data', async () => {
  const loadReport = vi.fn().mockRejectedValue({ status: 500, message: 'Service unavailable' });
  render(<CrossImageReport caseId="case-3" loadReport={loadReport} />);

  expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable');
  expect(screen.queryByText('跨镜像报告缺失')).not.toBeInTheDocument();
});
