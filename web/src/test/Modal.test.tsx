import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Modal from '../components/ui/Modal';

describe('Modal', () => {
  it('renders title and children into a dialog when open', () => {
    render(
      <Modal open onClose={vi.fn()} title="删除任务">
        <p>确认删除该任务吗？</p>
      </Modal>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('删除任务')).toBeInTheDocument();
    expect(screen.getByText('确认删除该任务吗？')).toBeInTheDocument();
  });

  it('applies the requested width class to the content', () => {
    render(
      <Modal open onClose={vi.fn()} title="宽弹窗" width="xl">
        内容
      </Modal>,
    );
    expect(screen.getByRole('dialog')).toHaveClass('max-w-4xl');
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <Modal open={false} onClose={vi.fn()} title="标题">
        内容
      </Modal>,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('the close button reports onClose exactly once', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="删除任务">
        内容
      </Modal>,
    );
    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape reports onClose', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="删除任务">
        内容
      </Modal>,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('keeps an accessible title and a working close button without a visible title', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose}>
        <p>无标题内容</p>
      </Modal>,
    );
    expect(screen.getByText('对话框')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('unmounts the dialog once open flips back to false', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <Modal open onClose={onClose} title="删除任务">
        内容
      </Modal>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '关闭' }));
    rerender(
      <Modal open={false} onClose={onClose} title="删除任务">
        内容
      </Modal>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
