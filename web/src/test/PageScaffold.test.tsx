import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Search } from 'lucide-react';
import { PageHeader, Segmented, StatStrip } from '../components/ui/PageScaffold';

describe('Segmented', () => {
  it('renders every option with its count and active state', () => {
    render(
      <Segmented
        value="all"
        onChange={() => {}}
        options={[
          { value: 'all', label: '全部', count: 12 },
          { value: 'deleted', label: '已删除' },
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: /全部/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /已删除/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('reports the clicked option through onChange', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Segmented
        value="all"
        onChange={onChange}
        options={[
          { value: 'all', label: '全部' },
          { value: 'deleted', label: '已删除' },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: /已删除/ }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('deleted');
  });
});

describe('StatStrip', () => {
  it('renders plain stats as non-interactive chips', () => {
    render(<StatStrip stats={[{ label: '文件', value: 128 }]} />);
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('文件')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('turns clickable stats into buttons and reports clicks', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { container } = render(
      <StatStrip
        stats={[
          { label: '全部', value: 10 },
          { label: '已删除', value: 3, onClick, active: true, dotClass: 'bg-rose-500' },
        ]}
      />,
    );
    const chip = screen.getByRole('button', { name: /已删除/ });
    expect(chip).toHaveClass('border-accent-300');
    expect(container.querySelector('span[aria-hidden="true"]')).toHaveClass('bg-rose-500');
    await user.click(chip);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('PageHeader', () => {
  it('renders title, subtitle and actions', () => {
    render(
      <PageHeader
        icon={Search}
        title="文件管理"
        subtitle="镜像内的全部文件"
        actions={<button type="button">导出</button>}
      />,
    );
    expect(screen.getByRole('heading', { level: 1, name: '文件管理' })).toBeInTheDocument();
    expect(screen.getByText('镜像内的全部文件')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出' })).toBeInTheDocument();
  });
});
