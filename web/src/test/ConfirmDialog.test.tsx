import { describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ConfirmDialog from '../components/ui/ConfirmDialog';

describe('ConfirmDialog', () => {
  it('renders the default title, message and button labels', () => {
    render(
      <ConfirmDialog open message="将删除该任务及其分析结果" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText('确认操作')).toBeInTheDocument();
    expect(screen.getByText('将删除该任务及其分析结果')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
  });

  it('respects custom confirm/cancel labels', () => {
    render(
      <ConfirmDialog
        open
        message="x"
        confirmText="立即删除"
        cancelText="再想想"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: '立即删除' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '再想想' })).toBeInTheDocument();
  });

  it('uses the danger variant only when danger is set', () => {
    const { rerender } = render(
      <ConfirmDialog open danger message="x" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: '确认' })).toHaveClass('btn-danger');
    expect(screen.getByRole('button', { name: '取消' })).not.toHaveClass('btn-danger');

    rerender(<ConfirmDialog open message="x" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole('button', { name: '确认' })).toHaveClass('btn-primary');
  });

  it('reports onConfirm when confirmed', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<ConfirmDialog open message="x" onConfirm={onConfirm} onCancel={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: '确认' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('disables the buttons and swaps in a spinner while the promise is pending', async () => {
    const user = userEvent.setup();
    let resolveConfirm: () => void = () => {};
    const onConfirm = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveConfirm = resolve;
        }),
    );
    render(
      <ConfirmDialog open message="x" confirmText="删除" onConfirm={onConfirm} onCancel={vi.fn()} />,
    );
    const confirmBtn = screen.getByRole('button', { name: '删除' });
    const cancelBtn = screen.getByRole('button', { name: '取消' });

    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirmBtn).toBeDisabled();
    expect(cancelBtn).toBeDisabled();
    expect(screen.getByRole('status')).toBeInTheDocument(); // Spinner
    expect(screen.queryByText('删除')).not.toBeInTheDocument();

    await act(async () => {
      resolveConfirm();
    });
    expect(screen.getByText('删除')).toBeInTheDocument();
    expect(confirmBtn).toBeEnabled();
    expect(cancelBtn).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('reports onCancel from the cancel button', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog open message="x" onConfirm={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('Escape routes through onCancel', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog open message="x" onConfirm={vi.fn()} onCancel={onCancel} />);
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <ConfirmDialog open={false} message="x" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
