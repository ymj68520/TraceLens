import { Route, Routes } from 'react-router-dom';
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import LegacyReportRedirect, { getReportTarget } from './LegacyReportRedirect';

function Destination() {
  return <div>new-report-route</div>;
}

test.each([
  ['/case-report?task_id=t1', '/case-intelligence?task_id=t1'],
  ['/case-report?taskId=t2', '/case-intelligence?task_id=t2'],
  ['/case-report?case_id=c1', '/case-intelligence?case_id=c1'],
])('redirects %s to the intelligence report route', (route) => {
  renderWithRouter(
    <Routes>
      <Route path="/case-report" element={<LegacyReportRedirect />} />
      <Route path="/case-intelligence" element={<Destination />} />
    </Routes>,
    { route },
  );

  expect(screen.getByText('new-report-route')).toBeInTheDocument();
});

test.each([
  ['task_id=t1', '/case-intelligence?task_id=t1'],
  ['taskId=t2', '/case-intelligence?task_id=t2'],
  ['case_id=c1', '/case-intelligence?case_id=c1'],
  ['', '/tasks'],
])('getReportTarget resolves %s to %s', (query, expected) => {
  expect(getReportTarget(new URLSearchParams(query))).toBe(expected);
});
