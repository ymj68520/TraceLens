import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';
import Login from './Login';
import { pythonApi } from '../services/api';
import { setFieldSession } from '../services/fieldSession';

vi.mock('../config/runtime', () => ({ FIELD_AUTH_ENABLED: true }));
vi.mock('../services/api', () => ({ pythonApi: { post: vi.fn() } }));
vi.mock('../services/fieldSession', () => ({ setFieldSession: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

test('field login uses server-issued bearer and never writes a mock token', async () => {
  pythonApi.post.mockResolvedValue({ access_token: 'signed-synthetic-token', token_type: 'bearer',
    principal: { id: 'analyst', role: 'analyst' } });
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByPlaceholderText('Enter username'), { target: { value: 'analyst' } });
  fireEvent.change(screen.getByPlaceholderText('Enter password'), { target: { value: 'synthetic-password' } });
  fireEvent.click(screen.getByRole('button', { name: /登录/ }));
  await waitFor(() => expect(setFieldSession).toHaveBeenCalledWith(
    'signed-synthetic-token', { id: 'analyst', role: 'analyst' }));
  expect(localStorage.getItem('auth_token')).toBeNull();
  expect(screen.queryByText(/任意用户名/)).not.toBeInTheDocument();
});

test('invalid login remains on page and does not create a session', async () => {
  pythonApi.post.mockRejectedValue(new Error('invalid credentials'));
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByPlaceholderText('Enter username'), { target: { value: 'analyst' } });
  fireEvent.change(screen.getByPlaceholderText('Enter password'), { target: { value: 'wrong-password' } });
  fireEvent.click(screen.getByRole('button', { name: /登录/ }));
  expect(await screen.findByText('登录失败，请重试')).toBeInTheDocument();
  expect(setFieldSession).not.toHaveBeenCalled();
});
