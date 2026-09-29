import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';
import LocalOperatorEntry from './LocalOperatorEntry';
import { getLocalOperatorSession } from '../services/localOperatorSession';
import { setFieldSession } from '../services/fieldSession';
vi.mock('../services/localOperatorSession', () => ({
  getLocalOperatorSession: vi.fn(), localReturnPath: (value) => value || '/dashboard',
}));
vi.mock('../services/fieldSession', () => ({ setFieldSession: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
const session = { access_token: 'unit-signed-session', principal: { id: 'local-auto-operator', role: 'admin' } };
function entry() {
  return render(<MemoryRouter initialEntries={[{ pathname: '/login', state: { returnTo: '/investigation?task_id=t1' } }]}>
    <Routes><Route path="/login" element={<LocalOperatorEntry />} />
      <Route path="/investigation" element={<p>工作台已进入</p>} /></Routes>
  </MemoryRouter>);
}
test('no username/password form; enters deep-linked workspace with actual returned session', async () => {
  getLocalOperatorSession.mockResolvedValue(session);
  entry();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(await screen.findByText('工作台已进入')).toBeInTheDocument();
  expect(setFieldSession).toHaveBeenCalledWith(session.access_token, session.principal);
});
test('unavailable bridge shows a retry, never falls back to anonymous', async () => {
  getLocalOperatorSession.mockRejectedValue(new Error('unavailable'));
  entry();
  expect(await screen.findByText('本机入口暂不可用，请检查本机服务。')).toBeInTheDocument();
  expect(setFieldSession).not.toHaveBeenCalled();
  getLocalOperatorSession.mockResolvedValue(session);
  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  await waitFor(() => expect(setFieldSession).toHaveBeenCalled());
});
