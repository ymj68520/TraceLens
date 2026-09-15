import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EmptyState from '../components/ui/EmptyState';
import { FolderSearch } from 'lucide-react';

describe('EmptyState', () => {
  it('renders title, description and default styling', () => {
    render(<EmptyState title="暂无数据" description="先选择一个任务" />);
    expect(screen.getByText('暂无数据')).toBeInTheDocument();
    expect(screen.getByText('先选择一个任务')).toBeInTheDocument();
  });

  it('omits the description block when not provided', () => {
    render(<EmptyState title="空" />);
    expect(screen.getByText('空')).toBeInTheDocument();
    expect(screen.queryByText(/先选择/)).not.toBeInTheDocument();
  });

  it('renders the icon slot and action button', () => {
    render(
      <EmptyState
        title="还没有任务"
        icon={<FolderSearch data-testid="icon" />}
        action={<button type="button">新建任务</button>}
      />,
    );
    expect(screen.getByTestId('icon')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新建任务' })).toBeInTheDocument();
  });
});
