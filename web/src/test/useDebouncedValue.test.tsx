import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { useDebouncedValue } from '../hooks/useUrlState';

function Harness({ value }: { value: string }) {
  const debounced = useDebouncedValue(value, 300);
  return <span data-testid="out">{debounced}</span>;
}

describe('useDebouncedValue', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns the initial value immediately without advancing timers', () => {
    vi.useFakeTimers();
    render(<Harness value="a" />);
    expect(screen.getByTestId('out').textContent).toBe('a');
  });

  it('propagates a new value only after the delay elapses', () => {
    vi.useFakeTimers();
    const { rerender } = render(<Harness value="a" />);
    rerender(<Harness value="b" />);
    // Not yet: the debounce window is still running.
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(screen.getByTestId('out').textContent).toBe('a');
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByTestId('out').textContent).toBe('b');
  });

  it('resets the timer when the value changes again mid-window', () => {
    vi.useFakeTimers();
    const { rerender } = render(<Harness value="a" />);
    rerender(<Harness value="b" />);
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender(<Harness value="c" />);
    // 300ms after the first change, but only 100ms after the second: still held.
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId('out').textContent).toBe('a');
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.getByTestId('out').textContent).toBe('c');
  });

  it('keeps the latest value when changes arrive faster than the delay', () => {
    vi.useFakeTimers();
    const { rerender } = render(<Harness value="1" />);
    rerender(<Harness value="2" />);
    rerender(<Harness value="3" />);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByTestId('out').textContent).toBe('3');
  });
});

describe('useDebouncedValue edge cases', () => {
  it('handles identical consecutive values without re-arming the timer', () => {
    vi.useFakeTimers();
    const { rerender } = render(<Harness value="same" />);
    rerender(<Harness value="same" />);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByTestId('out').textContent).toBe('same');
  });

  it('supports non-string values through the generic', () => {
    vi.useFakeTimers();
    function NumHarness({ value }: { value: number }) {
      const debounced = useDebouncedValue(value, 100);
      return <span data-testid="num">{debounced}</span>;
    }
    const { rerender } = render(<NumHarness value={1} />);
    rerender(<NumHarness value={2} />);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId('num').textContent).toBe('2');
  });
});
