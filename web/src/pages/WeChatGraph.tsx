import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { MessageCircle, RefreshCcw } from 'lucide-react';
import {
  getWeChatGraph,
  getWeChatChat,
  getWeChatGroupChat,
  getWeChatOwner,
  invalidateWeChatCache,
} from '../services/wechatService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { errorMessage, formatDateTime } from '../lib/utils';

interface WxNode {
  id: string;
  name?: string;
  nickname?: string;
  message_count?: number;
  [key: string]: unknown;
}

interface WxEdge {
  source: string | WxNode;
  target: string | WxNode;
  edge_type?: string;
  chatroom?: string;
  message_count?: number;
  [key: string]: unknown;
}

interface WxGraph {
  nodes?: WxNode[];
  edges?: WxEdge[];
  links?: WxEdge[];
}

interface ChatMessage {
  id?: string | number;
  sender?: string;
  content?: string;
  timestamp?: number | string;
  create_time?: number | string;
  [key: string]: unknown;
}

export default function WeChatGraph() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  const [graph, setGraph] = useState<{ nodes: WxNode[]; links: WxEdge[] }>({ nodes: [], links: [] });
  const [owner, setOwner] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<WxEdge | null>(null);
  const [selectedNode, setSelectedNode] = useState<WxNode | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const [g, o] = await Promise.all([
        getWeChatGraph(taskId) as Promise<WxGraph>,
        getWeChatOwner(taskId).catch(() => null),
      ]);
      setGraph({ nodes: g?.nodes ?? [], links: g?.links ?? g?.edges ?? [] });
      setOwner(o as Record<string, unknown> | null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadChat = useCallback(
    async (edge: WxEdge, offset = 0) => {
      if (!taskId) return;
      setChatLoading(true);
      try {
        const src = typeof edge.source === 'object' ? edge.source.id : edge.source;
        const tgt = typeof edge.target === 'object' ? edge.target.id : edge.target;
        const res = edge.edge_type === 'group' && edge.chatroom
          ? await getWeChatGroupChat(taskId, edge.chatroom, offset)
          : await getWeChatChat(taskId, src, tgt, offset);
        const list = (res as { messages?: ChatMessage[] })?.messages ?? [];
        setMessages((prev) => (offset === 0 ? list : [...prev, ...list]));
      } catch (err) {
        toast.error(`聊天记录加载失败：${errorMessage(err)}`);
      } finally {
        setChatLoading(false);
      }
    },
    [taskId, toast],
  );

  const handleInvalidate = async () => {
    if (!taskId) return;
    try {
      await invalidateWeChatCache(taskId);
      toast.success('缓存已失效，正在重新生成…');
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<MessageCircle size={36} />} title="未选择任务" description="请选择一个包含微信数据的任务。" />
      </div>
    );
  }

  if (loading) return <div className="card"><LoadingBlock text="正在加载关系图…" /></div>;
  if (error) return <div className="card"><EmptyState title="加载失败" description={error} /></div>;
  if (graph.nodes.length === 0) {
    return <div className="card"><EmptyState icon={<MessageCircle size={36} />} title="未发现微信聊天记录" /></div>;
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-4 h-[calc(100vh-9rem)]">
      {/* Graph canvas */}
      <Card padded={false} className="overflow-hidden flex flex-col">
        <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
          <h3 className="card-title">
            微信关系图
            {owner && <span className="ml-2 text-2xs font-normal text-ink-400">机主：{String(owner.nickname ?? owner.username ?? '')}</span>}
          </h3>
          <Button size="sm" variant="ghost" onClick={() => void handleInvalidate()}>
            <RefreshCcw size={13} /> 重建缓存
          </Button>
        </div>
        <div ref={wrapRef} className="flex-1 min-h-0">
          <ForceGraph2D
            graphData={graph as never}
            width={wrapRef.current?.clientWidth || 700}
            height={Math.max(400, (wrapRef.current?.clientHeight ?? 500) - 40)}
            nodeLabel={(n) => String((n as WxNode).nickname ?? (n as WxNode).name ?? (n as WxNode).id)}
            nodeColor={() => '#2e9b96'}
            nodeRelSize={6}
            linkColor={() => '#b4c0c3'}
            linkWidth={(l) => Math.max(1, Math.log2(Number((l as WxEdge).message_count ?? 1)))}
            backgroundColor="transparent"
            onLinkClick={(l) => {
              const edge = l as unknown as WxEdge;
              setSelectedEdge(edge);
              setSelectedNode(null);
              void loadChat(edge);
            }}
            onNodeClick={(n) => {
              setSelectedNode(n as WxNode);
              setSelectedEdge(null);
            }}
          />
        </div>
      </Card>

      {/* Side panel */}
      <Card padded={false} className="flex flex-col min-h-0">
        {selectedEdge ? (
          <>
            <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800">
              <h3 className="card-title">聊天记录</h3>
              <p className="text-2xs text-ink-400 mt-0.5 font-mono truncate">
                {String(typeof selectedEdge.source === 'object' ? selectedEdge.source.id : selectedEdge.source)}
                {' ↔ '}
                {String(typeof selectedEdge.target === 'object' ? selectedEdge.target.id : selectedEdge.target)}
              </p>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
              {chatLoading && messages.length === 0 ? (
                <LoadingBlock />
              ) : messages.length === 0 ? (
                <EmptyState title="暂无聊天记录" />
              ) : (
                messages.map((m, i) => (
                  <div key={m.id ?? i} className="text-xs">
                    <p className="text-2xs text-ink-400 mb-0.5">
                      {m.sender && <span className="font-medium text-ink-600 dark:text-ink-300">{m.sender} · </span>}
                      {formatDateTime(typeof m.timestamp === 'number' ? m.timestamp * 1000 : (m.create_time as string))}
                    </p>
                    <p className="bg-ink-50 dark:bg-ink-900 rounded-md px-2.5 py-1.5 text-ink-800 dark:text-ink-200 break-words">
                      {m.content ?? ''}
                    </p>
                  </div>
                ))
              )}
              {messages.length > 0 && (
                <Button size="sm" className="w-full" onClick={() => void loadChat(selectedEdge, messages.length)} disabled={chatLoading}>
                  {chatLoading ? '加载中…' : '加载更多'}
                </Button>
              )}
            </div>
          </>
        ) : selectedNode ? (
          <div className="p-4">
            <h3 className="card-title mb-2">联系人</h3>
            <dl className="space-y-1.5 text-xs">
              {Object.entries(selectedNode)
                .filter(([k]) => !['x', 'y', 'vx', 'vy', 'index'].includes(k))
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <dt className="text-ink-400">{k}</dt>
                    <dd className="text-ink-800 dark:text-ink-200 break-all text-right">{String(v)}</dd>
                  </div>
                ))}
            </dl>
          </div>
        ) : (
          <EmptyState title="点击节点或连线查看详情" description="节点为联系人，连线为会话关系（粗细代表消息量）。" />
        )}
      </Card>
    </div>
  );
}
