import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, test, vi } from 'vitest';

vi.mock('../../components/common/useToast', () => {
  // show 必须跨渲染稳定，否则页面加载列表的 effect 会随其引用变化重跑
  const show = vi.fn();
  return { useToast: () => ({ show }) };
});

vi.mock('../../services/wechatForensicsService', () => ({
  listWeChatImports: vi.fn(async () => ({
    imports: [{ import_id: 'w1', name: '微信导入', status: 'ready', message_count: 10 }],
  })),
  deleteWeChatImport: vi.fn(),
  getWeChatForensicsOverview: vi.fn(async () => ({ stats: { messages: 10 } })),
  createWeChatImport: vi.fn(),
  getWeChatSessions: vi.fn(async () => ({ sessions: [] })),
  getWeChatMessages: vi.fn(async () => ({ messages: [], total: 0 })),
  getWeChatContacts: vi.fn(async () => ({ contacts: [] })),
  getWeChatChatrooms: vi.fn(async () => ({ chatrooms: [] })),
}));

vi.mock('../../services/qqForensicsService', () => ({
  listQQImports: vi.fn(async () => ({
    imports: [{ import_id: 'q1', name: 'QQ 导入', status: 'ready', stats: { total_messages: 5 } }],
  })),
  deleteQQImport: vi.fn(),
  getQQForensicsOverview: vi.fn(async () => ({ stats: { total_messages: 5 } })),
  createQQImport: vi.fn(),
  getQQSessions: vi.fn(async () => ({ sessions: [] })),
  getQQMessages: vi.fn(async () => ({ messages: [], total: 0 })),
  getQQContacts: vi.fn(async () => ({ contacts: [] })),
  getQQChatrooms: vi.fn(async () => ({ chatrooms: [] })),
}));

vi.mock('../../services/wechatService', () => ({
  getWeChatGraph: vi.fn(async () => ({
    nodes: [{ id: 'a', label: 'A' }],
    edges: [],
    communities: [],
  })),
  getWeChatTimeline: vi.fn(async () => []),
  getWeChatChat: vi.fn(async () => ({ messages: [], total: 0 })),
  getWeChatGroupChat: vi.fn(async () => ({ messages: [], total: 0 })),
  invalidateWeChatCache: vi.fn(async () => ({})),
}));

// jsdom 无 canvas，力导向图只验证挂载不真渲染
vi.mock('./graph/components/GraphCanvas', () => ({
  default: () => <div data-testid="graph-canvas" />,
}));

import IMForensics from './IMForensics';

let location;
function Probe() {
  location = useLocation();
  return null;
}

const renderPage = (initialEntry = '/im-forensics') =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <IMForensics />
      <Probe />
    </MemoryRouter>,
  );

describe('IMForensics merged page', () => {
  test('shows the wechat empty state when nothing is imported', async () => {
    const { listWeChatImports } = await import('../../services/wechatForensicsService');
    listWeChatImports.mockResolvedValueOnce({ imports: [] });

    renderPage();
    expect(await screen.findByText('尚未导入微信账号数据库')).toBeInTheDocument();
  });

  test('loads the wechat import list, selects one and renders the six tabs', async () => {
    renderPage();

    expect(await screen.findByText('关系分析')).toBeInTheDocument();
    await waitFor(() => expect(location.search).toContain('import_id=w1'));
    for (const label of ['取证概览', '会话列表', '聊天记录', '联系人', '群聊']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(await screen.findByText('消息总数')).toBeInTheDocument();
  });

  test('switching platform rewrites platform/import params and loads qq imports', async () => {
    const { listQQImports } = await import('../../services/qqForensicsService');
    renderPage();

    await screen.findByText('关系分析');
    fireEvent.click(screen.getByRole('button', { name: 'QQ' }));

    await waitFor(() => expect(location.search).toContain('platform=qq'));
    await waitFor(() => expect(location.search).toContain('import_id=q1'));
    await waitFor(() => expect(listQQImports).toHaveBeenCalled());
  });

  test('a raw task_id drives the graph tab as an explicit data source', async () => {
    renderPage('/im-forensics?tab=graph&task_id=task-9');

    // 任务上下文覆盖时无需导入即可进入图谱 Tab，并给出数据源提示条
    expect(await screen.findByText('改用当前导入数据')).toBeInTheDocument();
    expect(screen.getByText(/task-9/)).toBeInTheDocument();
    expect(screen.getByTestId('graph-canvas')).toBeInTheDocument();
  });
});
