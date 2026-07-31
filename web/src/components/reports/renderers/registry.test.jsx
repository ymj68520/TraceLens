import { getReportRenderer, registerReportRenderer } from './registry';

function Custom() {
  return null;
}

test('returns generic table for unknown renderer and allows explicit registration', () => {
  expect(getReportRenderer('missing').displayName).toBe('GenericTableRenderer');
  registerReportRenderer('custom', Custom);
  expect(getReportRenderer('custom')).toBe(Custom);
});
