import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DetailRow, Drawer } from '../components/ui/Drawer';

describe('Drawer', () => {
  it('renders title, description and children when open', () => {
    render(
      <Drawer open onClose={vi.fn()} title="文件详情" description="/evidence/chat.db">
        <p>正文内容</p>
      </Drawer>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('文件详情')).toBeInTheDocument();
    expect(screen.getByText('/evidence/chat.db')).toBeInTheDocument();
    expect(screen.getByText('正文内容')).toBeInTheDocument();
  });

  it('falls back to the default 详情 title when none is given', () => {
    render(
      <Drawer open onClose={vi.fn()}>
        内容
      </Drawer>,
    );
    expect(screen.getByText('详情')).toBeInTheDocument();
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <Drawer open={false} onClose={vi.fn()} title="文件详情">
        内容
      </Drawer>,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('the close button reports onClose exactly once', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="文件详情">
        内容
      </Drawer>,
    );
    await user.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape reports onClose', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="文件详情">
        内容
      </Drawer>,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the footer slot', () => {
    render(
      <Drawer open onClose={vi.fn()} title="文件详情" footer={<button type="button">加入案件</button>}>
        内容
      </Drawer>,
    );
    expect(screen.getByRole('button', { name: '加入案件' })).toBeInTheDocument();
  });

  it('renders no footer strip when footer is omitted', () => {
    render(
      <Drawer open onClose={vi.fn()} title="文件详情">
        内容
      </Drawer>,
    );
    // The footer is the only strip carrying a top border (header uses border-b).
    expect(screen.getByRole('dialog').querySelector('[class*="border-t"]')).toBeNull();
  });
});

describe('DetailRow', () => {
  it('renders the label and value pair', () => {
    render(<DetailRow label="创建时间">2024-01-15 08:00:00</DetailRow>);
    expect(screen.getByText('创建时间')).toBeInTheDocument();
    expect(screen.getByText('2024-01-15 08:00:00')).toBeInTheDocument();
  });

  it('uses the mono font only when mono is set', () => {
    const { container, rerender } = render(<DetailRow label="MD5" mono>abc123</DetailRow>);
    expect(screen.getByText('abc123')).toHaveClass('font-mono');
    rerender(<DetailRow label="备注">普通文本</DetailRow>);
    expect(container.querySelector('span.font-mono')).toBeNull();
  });

  it('works inside an open drawer', () => {
    render(
      <Drawer open onClose={vi.fn()} title="事件详情">
        <DetailRow label="路径">/evidence/a.db</DetailRow>
        <DetailRow label="大小">2048</DetailRow>
      </Drawer>,
    );
    expect(screen.getByText('路径')).toBeInTheDocument();
    expect(screen.getByText('/evidence/a.db')).toBeInTheDocument();
    expect(screen.getByText('大小')).toBeInTheDocument();
  });
});
