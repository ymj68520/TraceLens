import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import TaskSelector from './TaskSelector';

vi.mock('../../store/taskSlice', () => ({
  fetchTasks: vi.fn(() => ({ type: 'tasks/fetch' })),
  setCurrentTask: vi.fn((task) => ({ type: 'tasks/setCurrent', payload: task })),
}));

function renderSelector(route) {
  const store = configureStore({
    reducer: {
      tasks: () => ({
        tasks: [],
        currentTask: null,
        status: 'loaded',
      }),
    },
  });

  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <TaskSelector />
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
