import { Route, Routes } from 'react-router-dom';
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import LegacyReportRedirect from './LegacyReportRedirect';
import { getReportTarget } from './reportRedirectTarget';

function Destination() {
  return <div>new-report-route</div>;
}

test.each([
  ['/case-report?task_id=t1', '/case-intelligence?task_id=t1&tab=forensic'],
  ['/case-report?taskId=t2', '/case-intelligence?task_id=t2&tab=forensic'],
  ['/case-report?case_id=c1', '/case-intelligence?case_id=c1&tab=forensic'],
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
  ['task_id=t1', '/case-intelligence?task_id=t1&tab=forensic'],
  ['taskId=t2', '/case-intelligence?task_id=t2&tab=forensic'],
  ['case_id=c1', '/case-intelligence?case_id=c1&tab=forensic'],
  ['', '/tasks'],
])('getReportTarget resolves %s to %s', (query, expected) => {
  expect(getReportTarget(new URLSearchParams(query))).toBe(expected);
});
