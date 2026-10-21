import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import AndroidArtifactsCard from './AndroidArtifactsCard';
import { getAndroidArtifacts, getAndroidArtifact } from '../services/evidenceIntakeService';

vi.mock('../services/evidenceIntakeService', () => ({
  getAndroidArtifacts: vi.fn(async () => ({ total: 1, page_size: 50, records: [{ id: 1, kind: 'calendar', package_name: 'calendar.app' }] })),
  getAndroidArtifact: vi.fn(async () => ({ record: { id: 1 }, source: { normalized_path: '/harmony/app/0/calendar.db', original_table: 'Events', original_primary_key: { _id: 7 } }, warning: 'WAL frame 未验证' })),
  captureAndroidArtifact: vi.fn(),
}));

describe('Harmony artifacts in the existing mobile view', () => {
  it('uses the mobile record kind and shows its original table and key', async () => {
    render(<MemoryRouter><AndroidArtifactsCard taskId="harmony" platform="HarmonyOS" /></MemoryRouter>);
    await waitFor(() => expect(getAndroidArtifacts).toHaveBeenCalledWith('harmony', 'mobile', '', 1));
    fireEvent.click(await screen.findByText('calendar.app', { exact: false }));
    await waitFor(() => expect(getAndroidArtifact).toHaveBeenCalledWith('harmony', 'mobile', 1));
    expect(await screen.findByText(/Events/)).toHaveTextContent('"_id":7');
    expect(screen.getByRole('button', { name: '将此单条记录加入调查研判' })).toBeInTheDocument();
  });
});
