import { render, screen, fireEvent } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import SelectionAuditPanel from './SelectionAuditPanel';
import api from '../../services/api';
vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));
test('用中文解释来源状态、代表数量和包含重试的预算', async () => {
  api.get.mockResolvedValue({ plan: { counts: { indexed: 100, candidates: 20, selected: 3, probed: 8, zero_bytes: 2 },
    usage: { used_calls: 4, max_calls: 6, reserved_tokens: 500, max_tokens: 1000 },
    family_counts: { browser: 2 }, probe_states: { metadata_only: 1 },
    display_candidates: [{ task_id: 't', source_id: 's', path: '/History', probe_state: 'metadata_only', selected: false, reason: '合法空内容，仅登记覆盖' }] } });
  render(<SelectionAuditPanel taskId="t" />);
  fireEvent.click(await screen.findByRole('button', { name: /候选选择审计/ }));
  expect(screen.getByText(/模型请求 4\/6/)).toBeInTheDocument();
  expect(screen.getByText(/浏览与通信数据库：2/)).toBeInTheDocument();
  expect(screen.getByText(/合法空内容/)).toBeInTheDocument();
});
