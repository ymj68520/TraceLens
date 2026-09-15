import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import Badge from '../components/ui/Badge';

describe('Badge', () => {
  it('renders its children as a chip', () => {
    render(<Badge tone="success">已完成</Badge>);
    expect(screen.getByText('已完成')).toBeInTheDocument();
  });

  it('prepends a status dot when dot is set', () => {
    const { container } = render(
      <Badge tone="danger" dot>
        已删除
      </Badge>,
    );
    const dot = container.querySelector('span[aria-hidden="true"]');
    expect(dot).not.toBeNull();
    expect(dot).toHaveClass('rounded-full');
    expect(dot).toHaveClass('bg-rose-500');
  });

  it('renders no dot by default', () => {
    const { container } = render(<Badge>普通</Badge>);
    expect(container.querySelector('span[aria-hidden="true"]')).toBeNull();
  });
});
