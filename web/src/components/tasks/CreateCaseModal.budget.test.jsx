import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import CreateCaseModal from './CreateCaseModal';

beforeEach(() => vi.clearAllMocks());

const fillRequired = (overrides = {}) => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const { container } = render(
    <CreateCaseModal onSubmit={onSubmit} onClose={() => {}} {...overrides} />
  );
  // The form has two comboboxes (priority first, budget second); address the
  // budget one by its accessible name.
  fireEvent.change(screen.getByPlaceholderText('例：某某网络诈骗案'), { target: { value: '预算测试案件' } });
  fireEvent.change(screen.getByPlaceholderText(/请描述案情背景/), { target: { value: '一起预算测试案件' } });
  return { onSubmit, container };
};

test('the default budget is omitted from the submitted options', async () => {
  const { onSubmit } = fillRequired();

  fireEvent.change(screen.getByPlaceholderText('/path/to/image.E01 or .dd'), {
    target: { value: '/evidence/disk.E01' },
  });
  fireEvent.click(screen.getByRole('button', { name: /创建案件/ }));

  await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
  expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('llmMaxFiles');
});

test('a chosen budget reaches the submitted options for new images', async () => {
  const { onSubmit } = fillRequired();

  fireEvent.change(screen.getByPlaceholderText('/path/to/image.E01 or .dd'), {
    target: { value: '/evidence/disk.E01' },
  });
  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: '500' } });
  fireEvent.click(screen.getByRole('button', { name: /创建案件/ }));

  await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
  expect(onSubmit.mock.calls[0][0]).toMatchObject({ llmMaxFiles: 500 });
});

test('an invalid custom budget blocks creating the case', async () => {
  const { onSubmit, container } = fillRequired();

  fireEvent.change(screen.getByPlaceholderText('/path/to/image.E01 or .dd'), {
    target: { value: '/evidence/disk.E01' },
  });
  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: 'custom' } });
  fireEvent.change(screen.getByLabelText('自定义分析文件上限'), { target: { value: '999999' } });
  fireEvent.submit(container.querySelector('form'));

  expect(await screen.findByText(/分析文件上限需在 1–100000 之间/)).toBeInTheDocument();
  expect(onSubmit).not.toHaveBeenCalled();
});
