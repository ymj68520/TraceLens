import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import TaskSelector from './TaskSelector';

vi.mock('../../store/taskSlice', () => ({
  fetchTasks: vi.fn(() => ({ type: 'tasks/fetch' })),
  setCurrentTask: vi.fn((task) => ({ type: 'tasks/setCurrent', payload: task })),
}));

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function renderSelector(route, tasks = []) {
  const store = configureStore({
    reducer: {
      tasks: () => ({
        tasks,
        currentTask: null,
        status: 'loaded',
      }),
    },
  });

  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <TaskSelector />
        <LocationProbe />
      </MemoryRouter>
    </Provider>,
  );
}

test('exposes the global task selector on the dedicated intelligence route', () => {
  renderSelector('/case-intelligence?taskId=task-A');

  expect(screen.getByRole('combobox')).toBeInTheDocument();
});

test('exposes the global task selector on the analysis center route', () => {
  renderSelector('/analysis-center?task_id=task-A');

  expect(screen.getByRole('combobox')).toBeInTheDocument();
});

test('exposes the global task selector on the final report viewer route', () => {
  renderSelector('/investigation/report?task_id=task-A');

  expect(screen.getByRole('combobox')).toBeInTheDocument();
});

test('switching tasks removes stale report, citation, and file identities', () => {
  renderSelector(
    '/investigation?task_id=old&report_id=rep-old&citation_id=c001&file=%2Fcase%2Fa.txt',
    [{ id: 'old', image_path: 'old.E01' }, { id: 'new', image_path: 'new.E01' }],
  );
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'new' } });

  expect(screen.getByTestId('location-search')).toHaveTextContent('task_id=new');
  expect(screen.getByTestId('location-search')).not.toHaveTextContent('rep-old');
  expect(screen.getByTestId('location-search')).not.toHaveTextContent('citation_id');
  expect(screen.getByTestId('location-search')).not.toHaveTextContent('file=');
});

test('switching Tasks in Android report mode clears the previous report import', () => {
  renderSelector(
    '/android?mode=report&task_id=old&import_id=old-report',
    [{ id: 'old', image_path: 'old.E01' }, { id: 'new', image_path: 'new.E01' }],
  );
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'new' } });
  expect(screen.getByTestId('location-search')).toHaveTextContent('task_id=new');
  expect(screen.getByTestId('location-search')).toHaveTextContent('mode=report');
  expect(screen.getByTestId('location-search')).not.toHaveTextContent('import_id=');
});
