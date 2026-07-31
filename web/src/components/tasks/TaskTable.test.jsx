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

  expect(screen.getByRole('link', { name: 'Report' })).toHaveAttribute(
    'href',
    '/reports/task/task-1',
  );
});
