import { screen } from '@testing-library/react';
import { renderWithRouter } from '../../test/renderWithRouter';
import TaskTable from './TaskTable';

test('completed task links to the versioned report workspace', () => {
  renderWithRouter(
    <TaskTable
      tasks={[{ id: 'task-1', status: 'completed', timestamps: {}, progress: {} }]}
      onCancel={() => {}}
      onDelete={() => {}}
      onJoinCase={() => {}}
    />,
  );

  expect(screen.getByRole('link', { name: '报告' })).toHaveAttribute(
    'href',
    '/reports/task/task-1',
  );
});

test('cloud task keeps the export name and verification hashes while readers use the RAW', () => {
  renderWithRouter(<TaskTable tasks={[{ id: 'cloud', status: 'completed', android_source: 'aliyun-image',
    image_path: '/tasks/cloud/work/aliyun_image/system.raw', timestamps: {}, progress: {},
    metadata: { source_label: 'file_m-test_system.raw.tar.gz', aliyun_prepared: 'true',
      preflight_source_sha256: 'a'.repeat(64), aliyun_raw_sha256: 'b'.repeat(64) },
  }]} />);
  expect(screen.getByText('file_m-test_system.raw.tar.gz')).toBeInTheDocument();
  expect(screen.getByText('阿里云镜像 · RAW 已校验')).toHaveAttribute('title', expect.stringContaining('a'.repeat(64)));
  expect(screen.getByRole('link', { name: '文件' })).toHaveAttribute('href', '/files?task_id=cloud');
  expect(screen.getByRole('link', { name: '报告' })).toHaveAttribute('href', '/reports/task/cloud');
});
