import { screen } from '@testing-library/react';
import { renderWithRouter } from './renderWithRouter';

function Smoke() {
  return <h1>Report test harness</h1>;
}

test('renders React components in jsdom', () => {
  renderWithRouter(<Smoke />);
  expect(screen.getByRole('heading', { name: 'Report test harness' })).toBeInTheDocument();
});
