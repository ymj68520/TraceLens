import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import VersionHistory from './VersionHistory';

const versionOne = { report_id: 'r1', version: 1, status: 'ready' };
const versionTwo = { report_id: 'r2', version: 2, status: 'generating', progress: 20 };

test('selects the version clicked in the history', () => {
  const onSelect = vi.fn();
  render(<VersionHistory versions={[versionTwo, versionOne]} selectedVersion={versionTwo} onSelect={onSelect} />);

  fireEvent.click(screen.getByRole('radio', { name: '版本 1' }));

  expect(onSelect).toHaveBeenCalledWith(versionOne);
});
