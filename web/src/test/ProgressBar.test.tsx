import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProgressBar from '../components/ui/ProgressBar';

describe('ProgressBar', () => {
  it('maps the value to the fill width', () => {
    render(<ProgressBar value={40} />);
    const fill = document.querySelector('.h-full.rounded-full') as HTMLElement;
    expect(fill).toBeInTheDocument();
    expect(fill.style.width).toBe('40%');
  });

  it('clamps out-of-range values', () => {
    const { rerender } = render(<ProgressBar value={150} />);
    let fill = document.querySelector('.h-full.rounded-full') as HTMLElement;
    expect(fill.style.width).toBe('100%');
    rerender(<ProgressBar value={-20} />);
    fill = document.querySelector('.h-full.rounded-full') as HTMLElement;
    expect(fill.style.width).toBe('0%');
  });

  it('shows the mono percentage label when requested', () => {
    render(<ProgressBar value={73} showLabel />);
    expect(screen.getByText('73%')).toHaveClass('font-mono');
  });

  it('hides the label by default', () => {
    render(<ProgressBar value={50} />);
    expect(screen.queryByText('50%')).not.toBeInTheDocument();
  });
});
