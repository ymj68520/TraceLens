import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { LayoutDashboard } from 'lucide-react';
import KpiCard from '../pages/dashboard/components/KpiCard';

type FrameCallback = (timeMs: number) => void;

/** The fake clock + rAF queue driving useCountUp deterministically. */
let nowMs = 0;
let frameQueue: FrameCallback[] = [];

function runFrames(elapsedMs: number): void {
  nowMs += elapsedMs;
  const pending = frameQueue;
  frameQueue = [];
  for (const cb of pending) cb(nowMs);
}

beforeEach(() => {
  nowMs = 0;
  frameQueue = [];
  vi.stubGlobal('performance', { now: () => nowMs });
  vi.stubGlobal('requestAnimationFrame', (cb: FrameCallback) => {
    frameQueue.push(cb);
    return frameQueue.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {});
  // recharts' ResponsiveContainer (sparkline) needs it under jsdom.
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const baseProps = {
  label: '任务总数',
  hint: '含全部状态的任务',
  Icon: LayoutDashboard,
  iconClass: 'bg-accent-50 text-accent-600',
  isDark: false,
};

/** The animated number lives in the only <span> inside a <p>. */
function valueEl(container: HTMLElement): HTMLSpanElement {
  const el = container.querySelector<HTMLSpanElement>('p span');
  if (!el) throw new Error('KpiCard value span not found');
  return el;
}

describe('KpiCard', () => {
  it('renders label, hint and the icon chip', () => {
    const { container } = render(<KpiCard {...baseProps} value={5} />);
    expect(screen.getByText('任务总数')).toBeInTheDocument();
    expect(screen.getByText('含全部状态的任务')).toBeInTheDocument();
    expect(container.querySelector('svg')).not.toBeNull();
    expect(container.querySelector('span.bg-accent-50')).not.toBeNull();
  });

  it('shows the plain value before the first animation frame fires', () => {
    const { container } = render(<KpiCard {...baseProps} value={5} />);
    expect(valueEl(container).textContent).toBe('5');
  });

  it('counts up from zero to the target across frames, then stops the loop', () => {
    const { container } = render(<KpiCard {...baseProps} value={120} />);

    runFrames(0); // p = 0 → eased 0 → still at the start
    expect(valueEl(container).textContent).toBe('0');

    runFrames(250); // p = 0.5, eased 0.875 → round(120 * 0.875)
    expect(valueEl(container).textContent).toBe('105');

    runFrames(250); // p = 1 → exact target
    expect(valueEl(container).textContent).toBe('120');
    expect(frameQueue).toHaveLength(0); // finished animation requests no more frames
  });

  it('re-animates from the previous value when the target changes', () => {
    const { container, rerender } = render(<KpiCard {...baseProps} value={120} />);
    runFrames(0);
    runFrames(500);
    expect(valueEl(container).textContent).toBe('120');

    rerender(<KpiCard {...baseProps} value={300} />);
    runFrames(0); // first frame of the new tween: still at 120
    expect(valueEl(container).textContent).toBe('120');

    runFrames(500); // tween completes at the new target
    expect(valueEl(container).textContent).toBe('300');
    expect(frameQueue).toHaveLength(0);
  });

  it('renders the sparkline only for series that qualify', () => {
    const { container, unmount } = render(<KpiCard {...baseProps} value={1} spark={[1, 2, 3]} />);
    expect(container.querySelector('div.h-9.w-20')).not.toBeNull();
    unmount();

    const bare = render(<KpiCard {...baseProps} value={1} />);
    expect(bare.container.querySelector('div.h-9.w-20')).toBeNull();
  });
});
