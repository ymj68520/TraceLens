import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import ReportWorkspace from './ReportWorkspace';

const manifest = {
  report_id: 'report-1',
  directory: [
    {
      id: 'phone',
      title: 'Phone image',
      children: [
        {
          id: 'android',
          title: 'Android',
          children: [
            {
              category_id: 'android.sms', evidence_id: 'phone', platform: 'android',
              title: '短信', renderer: 'chat', total: 2, deleted: 1, recovered: 0,
              high_risk: 1, relevant: 1, referenced: 0, page_size: 1, pages: 2,
              page_paths: ['sms-1.json', 'sms-2.json'],
            },
          ],
        },
        {
          id: 'linux',
          title: 'Linux',
          children: [
            {
              category_id: 'linux.shell', evidence_id: 'phone', platform: 'linux',
              title: 'Shell 历史', renderer: 'table', total: 1, deleted: 0, recovered: 0,
              high_risk: 0, relevant: 0, referenced: 0, page_size: 100, pages: 1,
              page_paths: ['shell-1.json'],
            },
          ],
        },
      ],
    },
  ],
  categories: [
    {
      category_id: 'android.sms', evidence_id: 'phone', platform: 'android',
      title: '短信', renderer: 'chat', total: 2, deleted: 1, recovered: 0,
      high_risk: 1, relevant: 1, referenced: 0, page_size: 1, pages: 2,
      page_paths: ['sms-1.json', 'sms-2.json'],
    },
    {
      category_id: 'linux.shell', evidence_id: 'phone', platform: 'linux',
      title: 'Shell 历史', renderer: 'table', total: 1, deleted: 0, recovered: 0,
      high_risk: 0, relevant: 0, referenced: 0, page_size: 100, pages: 1,
      page_paths: ['shell-1.json'],
    },
  ],
};

function Harness({ dataSource, initialCategory = 'android.sms', initialPage = 1, searchState }) {
  const [selectedCategory, setSelectedCategory] = useState(initialCategory);
  const [selectedPage, setSelectedPage] = useState(initialPage);
  const [directoryOpen, setDirectoryOpen] = useState(false);

  return (
    <ReportWorkspace
      manifest={manifest}
      dataSource={dataSource}
      reportId="report-1"
      selectedCategory={selectedCategory}
      selectedPage={selectedPage}
      onSelectCategory={(categoryId, page = 1) => {
        setSelectedCategory(categoryId);
        setSelectedPage(page);
      }}
      onSelectPage={setSelectedPage}
      searchState={searchState || {
        query: '', result: { total: 0, hits: [] }, currentHit: null, cursor: 0,
        loading: false, error: null, submit: vi.fn(), next: vi.fn(), previous: vi.fn(),
      }}
      directoryOpen={directoryOpen}
      onDirectoryOpenChange={setDirectoryOpen}
    />
  );
}

function categoryPage(categoryId, page, records = []) {
  const category = manifest.categories.find((item) => item.category_id === categoryId);
  return {
    schema_version: '1.0', category_id: categoryId, page,
    page_size: category.page_size, total: category.total, records, sha256: 'digest',
  };
}

test('opens the mobile directory, renders only manifest leaves, selects a category, and closes the drawer', async () => {
  const user = userEvent.setup();
  const source = {
    getCategoryPage: vi.fn((_, categoryId, page) => Promise.resolve(categoryPage(categoryId, page))),
  };
  render(<Harness dataSource={source} />);

  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledWith('report-1', 'android.sms', 1));
  const toggle = screen.getByRole('button', { name: '打开报告目录' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');

  await user.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const directory = screen.getByRole('complementary', { name: '报告目录' });
  expect(within(directory).getByRole('button', { name: '打开 短信' })).toHaveTextContent('已删除 1');
  expect(within(directory).getByRole('button', { name: '打开 短信' })).toHaveTextContent('高风险 1');
  expect(within(directory).getByRole('button', { name: '打开 短信' })).toHaveTextContent('重点 1');
  expect(within(directory).queryByRole('button', { name: '打开 Phone image' })).not.toBeInTheDocument();
  expect(within(directory).queryByRole('button', { name: '打开 Android' })).not.toBeInTheDocument();

  await user.click(within(directory).getByRole('button', { name: '打开 Shell 历史' }));
  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledWith('report-1', 'linux.shell', 1));
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(source.getCategoryPage).toHaveBeenCalledTimes(2);
});

test('clamps pagination input and requests only valid selected pages', async () => {
  const user = userEvent.setup();
  const source = {
    getCategoryPage: vi.fn((_, categoryId, page) => Promise.resolve(categoryPage(categoryId, page))),
  };
  render(<Harness dataSource={source} />);

  await waitFor(() => expect(screen.getByLabelText('页码')).toHaveValue('1'));
  let pageInput = screen.getByLabelText('页码');
  await user.clear(pageInput);
  await user.type(pageInput, '99');
  await user.keyboard('{Enter}');

  await waitFor(() => expect(source.getCategoryPage).toHaveBeenLastCalledWith('report-1', 'android.sms', 2));
  await waitFor(() => expect(screen.getByLabelText('页码')).toHaveValue('2'));

  pageInput = screen.getByLabelText('页码');
  await user.clear(pageInput);
  await user.type(pageInput, '0');
  await user.keyboard('{Enter}');
  await waitFor(() => expect(source.getCategoryPage).toHaveBeenLastCalledWith('report-1', 'android.sms', 1));
  await waitFor(() => expect(screen.getByLabelText('页码')).toHaveValue('1'));

  pageInput = screen.getByLabelText('页码');
  const callsBeforeNaN = source.getCategoryPage.mock.calls.length;
  await user.clear(pageInput);
  await user.type(pageInput, 'abc');
  await user.keyboard('{Enter}');
  expect(source.getCategoryPage).toHaveBeenCalledTimes(callsBeforeNaN);
  expect(screen.getByLabelText('页码')).toHaveValue('1');
});

test('navigates a record search hit once and scrolls after its category page renders', async () => {
  const scrollIntoView = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = scrollIntoView;
  const source = {
    getCategoryPage: vi.fn((_, categoryId, page) => Promise.resolve(categoryPage(
      categoryId,
      page,
      categoryId === 'linux.shell'
        ? [{ record_id: 'rec:special[1]', title: 'root login', fields: { command: 'sudo -i' } }]
        : [],
    ))),
  };
  const hit = { record_id: 'rec:special[1]', category_id: 'linux.shell', page: 1 };

  render(<Harness dataSource={source} searchState={{
    query: 'root', result: { total: 1, hits: [hit] }, currentHit: hit, cursor: 0,
    loading: false, error: null, submit: vi.fn(), next: vi.fn(), previous: vi.fn(),
  }} />);

  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledWith('report-1', 'linux.shell', 1));
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
  expect(screen.getByText('root login').closest('[data-record-id]')).toHaveAttribute('data-record-id', 'rec:special[1]');
  expect(source.getCategoryPage).toHaveBeenCalledTimes(2);

  Element.prototype.scrollIntoView = original;
});

test('reactivates the same hit when its search activation revision changes', async () => {
  const user = userEvent.setup();
  const scrollIntoView = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = scrollIntoView;
  const source = {
    getCategoryPage: vi.fn((_, categoryId, page) => Promise.resolve(categoryPage(
      categoryId,
      page,
      categoryId === 'linux.shell'
        ? [{ record_id: 'same-hit', title: 'same result', fields: {} }]
        : [],
    ))),
  };
  const hit = { record_id: 'same-hit', category_id: 'linux.shell', page: 1 };
  const searchState = (activation) => ({
    query: 'same', result: { total: 1, hits: [hit] }, currentHit: hit, cursor: 0,
    activation, loading: false, error: null,
    submit: vi.fn(), next: vi.fn(), previous: vi.fn(),
  });

  const view = render(<Harness dataSource={source} searchState={searchState(1)} />);
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));

  await user.click(screen.getByRole('button', { name: '打开 短信' }));
  await waitFor(() => expect(source.getCategoryPage).toHaveBeenLastCalledWith('report-1', 'android.sms', 1));

  view.rerender(<Harness dataSource={source} searchState={searchState(2)} />);
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
  expect(source.getCategoryPage).toHaveBeenLastCalledWith('report-1', 'linux.shell', 1);

  const callsAfterReactivation = source.getCategoryPage.mock.calls.length;
  view.rerender(<Harness dataSource={source} searchState={searchState(2)} />);
  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledTimes(callsAfterReactivation));
  expect(scrollIntoView).toHaveBeenCalledTimes(2);

  Element.prototype.scrollIntoView = original;
});

test('navigates a section hit without attempting record scrolling', async () => {
  const scrollIntoView = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = scrollIntoView;
  const source = {
    getCategoryPage: vi.fn((_, categoryId, page) => Promise.resolve(categoryPage(categoryId, page))),
  };
  const hit = { kind: 'section', category_id: 'linux.shell', page: 1 };

  render(<Harness dataSource={source} searchState={{
    query: 'shell', result: { total: 1, hits: [hit] }, currentHit: hit, cursor: 0,
    loading: false, error: null, submit: vi.fn(), next: vi.fn(), previous: vi.fn(),
  }} />);

  await waitFor(() => expect(source.getCategoryPage).toHaveBeenCalledWith('report-1', 'linux.shell', 1));
  expect(scrollIntoView).not.toHaveBeenCalled();

  Element.prototype.scrollIntoView = original;
});
