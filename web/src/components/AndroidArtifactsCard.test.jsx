import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import AndroidArtifactsCard from './AndroidArtifactsCard';
import { captureAndroidArtifact, getAndroidArtifact, getAndroidArtifacts } from '../services/evidenceIntakeService';
import { MemoryRouter, useLocation } from 'react-router-dom';

vi.mock('../services/evidenceIntakeService', () => ({
  captureAndroidArtifact: vi.fn(), getAndroidArtifact: vi.fn(), getAndroidArtifacts: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());
const LocationProbe = () => <span data-testid="location-probe">{useLocation().pathname}{useLocation().search}</span>;
const renderCard = () => render(<MemoryRouter><AndroidArtifactsCard taskId="synthetic-task" /><LocationProbe /></MemoryRouter>);

test('shows AndroidAnalyzer rows and labels source as candidate, never verified row', async () => {
  getAndroidArtifacts.mockResolvedValue({ total: 1, page_size: 50, records: [
    { id: 7, body: '合成短信', address: '10086' },
  ] });
  getAndroidArtifact.mockResolvedValue({ record: { id: 7, body: '合成短信' },
    source: { normalized_path: 'data/data/telephony/mmssms.db', original_path: '/member/mmssms.db', sha256: 'abc' },
    warning: '候选文件不能证明原始行' });
  renderCard();
  fireEvent.click(await screen.findByRole('button', { name: /合成短信/ }));
  expect(await screen.findByText(/候选文件不能证明原始行/)).toBeInTheDocument();
  expect(screen.getByText(/原始路径：/)).toHaveTextContent('/member/mmssms.db');
  expect(getAndroidArtifact).toHaveBeenCalledWith('synthetic-task', 'sms', 7);
});

test('does not hide field access failure', async () => {
  getAndroidArtifacts.mockRejectedValue({ data: { detail: 'field access is not configured' } });
  renderCard();
  expect(await screen.findByRole('alert')).toHaveTextContent('field access is not configured');
});

test('only explicitly selected frozen row navigates to its exact investigation key', async () => {
  const key = `android_artifact:v1:synthetic-task:${'a'.repeat(64)}:sms:7`;
  getAndroidArtifacts.mockResolvedValue({ total: 1, page_size: 50, records: [{ id: 7, body: '合成短信' }] });
  getAndroidArtifact.mockResolvedValue({ record: { id: 7, body: '合成短信' },
    record_hash: 'h'.repeat(64), source_revision: 'r'.repeat(64), source: null, warning: '候选来源' });
  captureAndroidArtifact.mockResolvedValue({ evidence_key: key });
  renderCard();
  fireEvent.click(await screen.findByRole('button', { name: /合成短信/ }));
  fireEvent.click(await screen.findByRole('button', { name: /将此单条记录加入调查研判/ }));
  expect(captureAndroidArtifact).toHaveBeenCalledWith('synthetic-task', 'sms', 7, 'h'.repeat(64), 'r'.repeat(64));
  await waitFor(() => expect(screen.getByTestId('location-probe')).toHaveTextContent(`evidence_key=${encodeURIComponent(key)}`));
});
