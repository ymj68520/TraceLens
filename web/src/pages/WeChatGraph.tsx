import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  AlertTriangle,
  BarChart3,
  CalendarClock,
  MessageCircle,
  MessagesSquare,
  Network,
  RefreshCcw,
  Users,
} from 'lucide-react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import { PageHeader, Segmented } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import {
  getWeChatGraph,
  getWeChatChat,
  getWeChatGroupChat,
  getWeChatOwner,
  getWeChatTimeline,
  invalidateWeChatCache,
} from '../services/wechatService';
import { errorMessage } from '../lib/utils';
import { emitAppEvent } from '../lib/appEvents';
import { useUrlState } from '../hooks/useUrlState';
import StatsCards, { type StatCardItem } from './wechat/StatsCards';
import ContactsPanel from './wechat/ContactsPanel';
import ContactDrawer from './wechat/ContactDrawer';
import ChatRecordsPanel from './wechat/ChatRecordsPanel';
import GraphLegend from './wechat/GraphLegend';
import TrendChartPanel from './wechat/TrendChartPanel';
import { useElementSize } from './wechat/useElementSize';
import {
  CHAT_PAGE_SIZE,
  computeMessageTotal,
  displayName,
  edgeEndpoints,
  edgeKey,
  findEdgeByKey,
  isGroupEdge,
  isGroupNode,
  parseTimeline,
  unwrapOwner,
  type ChatMessage,
  type TimelineSummary,
  type WxEdge,
  type WxGraphData,
  type WxNode,
} from './wechat/wechatUtils';

/* 设计语言：青色 accent 系；群聊节点用 sky 区分；选中用 amber 高亮。 */
const NODE_OWNER_COLOR = '#0d8a89';
const NODE_COLOR = '#17aaa8';
const NODE_GROUP_COLOR = '#38bdf8';
const NODE_SELECTED_COLOR = '#f59e0b';
const LINK_DM_COLOR = 'rgba(23,170,168,0.35)';
const LINK_GROUP_COLOR = 'rgba(56,189,248,0.45)';
const LINK_HIGHLIGHT_COLOR = 'rgba(13,138,137,0.9)';

export default function WeChatGraph() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  // URL 持久化：选中联系人 / 会话 / 联系人排序 / 消息类型筛选 / 右栏 tab。
  const [contactParam, setContactParam] = useUrlState('contact', '');
  const [chatParam, setChatParam] = useUrlState('chat', '');
  const [sort, setSort] = useUrlState('csort', 'msgs');
  const [mtype, setMtype] = useUrlState('mtype', 'all');
  const [wtab, setWtab] = useUrlState('wtab', 'chat');

  const [graph, setGraph] = useState<{ nodes: WxNode[]; links: WxEdge[] }>({ nodes: [], links: [] });
  const [owner, setOwner] = useState<Record<string, unknown> | null>(null);
  const [trend, setTrend] = useState<TimelineSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [chatTotal, setChatTotal] = useState<number | null>(null);
  const [lastCount, setLastCount] = useState(0);

  const [drawerNode, setDrawerNode] = useState<WxNode | null>(null);

  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const { ref: wrapRef, size } = useElementSize<HTMLDivElement>();
  const graphRef = useRef<{ nodes: WxNode[] }>({ nodes: [] });
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  /* ------------------------------ 数据加载 ------------------------------ */

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const [g, o, tl] = await Promise.all([
        getWeChatGraph(taskId) as Promise<WxGraphData>,
        getWeChatOwner(taskId).catch(() => null),
        getWeChatTimeline(taskId, 'day').catch(() => null),
      ]);
      setGraph({ nodes: g?.nodes ?? [], links: g?.links ?? g?.edges ?? [] });
      setOwner(unwrapOwner(o));
      setTrend(parseTimeline(tl));
      emitAppEvent({ kind: 'info', title: '微信关系数据加载完成', detail: `联系人 ${g?.nodes?.length ?? 0} 位` });
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
    async (edge: WxEdge, offset: number) => {
      if (!taskId) return;
      if (offset === 0) {
        setChatLoading(true);
        setMessages([]);
      } else {
        setLoadingMore(true);
      }
      try {
        const { src, tgt } = edgeEndpoints(edge);
        const res = (isGroupEdge(edge) && typeof edge.chatroom === 'string' && edge.chatroom
          ? await getWeChatGroupChat(taskId, edge.chatroom, offset)
          : await getWeChatChat(taskId, src, tgt, offset)) as
          | { messages?: ChatMessage[]; total?: number }
          | undefined;
        const list = res?.messages ?? [];
        setLastCount(list.length);
        if (offset === 0) setChatTotal(typeof res?.total === 'number' ? res.total : null);
        setMessages((prev) => (offset === 0 ? list : [...prev, ...list]));
      } catch (err) {
        toast.error(`聊天记录加载失败：${errorMessage(err)}`);
      } finally {
        setChatLoading(false);
        setLoadingMore(false);
      }
    },
    [taskId, toast],
  );

  // URL / 图谱变化时还原会话选择（invalidate 重建后同样生效）。
  useEffect(() => {
    if (!taskId || !chatParam || graph.links.length === 0) return;
    const edge = findEdgeByKey(graph.links, chatParam);
    if (!edge) return;
    void loadChat(edge, 0);
  }, [taskId, chatParam, graph.links, loadChat]);

  const handleInvalidate = async () => {
    if (!taskId) return;
    try {
      await invalidateWeChatCache(taskId);
      toast.info('缓存已失效，正在重新生成…');
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  /* ------------------------------ 派生数据 ------------------------------ */

  const ownerId = useMemo(() => {
    if (!owner) return null;
    for (const k of ['username', 'wxid', 'id', 'alias']) {
      const v = owner[k];
      if (typeof v === 'string' && v) return v;
    }
    return null;
  }, [owner]);

  const counts = useMemo(() => {
    const groupNodes = graph.nodes.filter((n) => isGroupNode(n)).length;
    const groupEdges = graph.links.filter((e) => isGroupEdge(e)).length;
    return {
      contacts: graph.nodes.length - groupNodes,
      groups: groupNodes,
      dm: graph.links.length - groupEdges,
      groupEdges,
    };
  }, [graph]);

  const msgTotal = useMemo(() => computeMessageTotal(graph.nodes, graph.links), [graph]);
  const ownerInGraph = ownerId != null && graph.nodes.some((n) => n.id === ownerId);

  const selectedEdge = useMemo(
    () => (chatParam ? findEdgeByKey(graph.links, chatParam) : null),
    [chatParam, graph.links],
  );

  const hasMore = useMemo(() => {
    if (messages.length === 0) return false;
    if (chatTotal != null) return messages.length < chatTotal;
    return lastCount >= CHAT_PAGE_SIZE;
  }, [messages.length, chatTotal, lastCount]);

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    graph.nodes.forEach((n) => m.set(n.id, displayName(n)));
    return m;
  }, [graph]);

  const edgeParticipants = useCallback(
    (edge: WxEdge): string => {
      if (isGroupEdge(edge) && typeof edge.chatroom === 'string' && edge.chatroom) return edge.chatroom;
      const { src, tgt } = edgeEndpoints(edge);
      return `${nameById.get(src) ?? src} ↔ ${nameById.get(tgt) ?? tgt}`;
    },
    [nameById],
  );

  const statCards: StatCardItem[] = [
    {
      icon: MessagesSquare,
      tone: 'bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300',
      label: '消息总数',
      value: msgTotal.value != null ? String(msgTotal.value) : '—',
      sub:
        msgTotal.source === 'edge'
          ? '按会话边汇总'
          : msgTotal.source === 'node'
            ? '按联系人汇总'
            : '接口未返回消息计数字段',
    },
    {
      icon: Users,
      tone: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300',
      label: '联系人',
      value: String(counts.contacts),
      sub: counts.groups > 0 ? `另含群聊 ${counts.groups} 个` : '不含群聊',
    },
    {
      icon: Network,
      tone: 'bg-violet-100 dark:bg-violet-500/15 text-violet-700 dark:text-violet-300',
      label: '会话关系',
      value: String(graph.links.length),
      sub: counts.groupEdges > 0 ? `含群会话 ${counts.groupEdges} 条` : '双人会话',
    },
    {
      icon: CalendarClock,
      tone: 'bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
      label: '活跃峰值',
      value: trend?.peak?.label ?? '—',
      sub: trend?.peak ? `${trend.peak.count} 条消息` : '时间线接口不可用',
    },
  ];

  /* ------------------------------ 图谱交互 ------------------------------ */

  const centerOnNode = useCallback((id: string, attempts = 10) => {
    const node = graphRef.current.nodes.find((n) => n.id === id);
    const fg = fgRef.current;
    if (node && typeof node.x === 'number' && typeof node.y === 'number' && fg) {
      fg.centerAt(node.x, node.y, 500);
      fg.zoom(1.6, 500);
      return;
    }
    // 模拟尚未收敛时（坐标未生成）稍后重试。
    if (attempts > 0) {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => centerOnNode(id, attempts - 1), 250);
    }
  }, []);

  const handleSelectContact = useCallback(
    (node: WxNode) => {
      setContactParam(node.id);
      setDrawerNode(node);
      centerOnNode(node.id);
    },
    [setContactParam, centerOnNode],
  );

  const handleGraphNodeClick = useCallback(
    (n: object) => {
      const node = n as WxNode;
      if (!node.id) return;
      setContactParam(node.id);
      centerOnNode(node.id);
    },
    [setContactParam, centerOnNode],
  );

  const handleGraphLinkClick = useCallback(
    (l: object) => {
      const edge = l as unknown as WxEdge;
      setChatParam(edgeKey(edge));
      setWtab('chat');
    },
    [setChatParam, setWtab],
  );

  // 图谱首次布局后整体缩放适配。
  useEffect(() => {
    if (graph.nodes.length === 0) return;
    const t = window.setTimeout(() => fgRef.current?.zoomToFit(400, 40), 1000);
    return () => window.clearTimeout(t);
  }, [graph]);

  // 带 contact 参数进入页面时，图谱加载完成后自动定位一次。
  const didAutoCenterRef = useRef(false);
  useEffect(() => {
    if (!didAutoCenterRef.current && graph.nodes.length > 0 && contactParam) {
      didAutoCenterRef.current = true;
      centerOnNode(contactParam);
    }
  }, [graph.nodes.length, contactParam, centerOnNode]);

  const nodeColor = useCallback(
    (n: object) => {
      const node = n as WxNode;
      if (contactParam && node.id === contactParam) return NODE_SELECTED_COLOR;
      if (ownerInGraph && node.id === ownerId) return NODE_OWNER_COLOR;
      return isGroupNode(node) ? NODE_GROUP_COLOR : NODE_COLOR;
    },
    [contactParam, ownerInGraph, ownerId],
  );

  const nodeVal = useCallback((n: object) => {
    const mc = (n as WxNode).message_count;
    return 1 + Math.min(4, Math.log2(1 + (typeof mc === 'number' ? mc : 0)));
  }, []);

  const nodeLabel = useCallback((n: object) => displayName(n as WxNode), []);

  const linkColor = useCallback(
    (l: object) => {
      const edge = l as WxEdge;
      if (contactParam) {
        const { src, tgt } = edgeEndpoints(edge);
        if (src === contactParam || tgt === contactParam) return LINK_HIGHLIGHT_COLOR;
      }
      return isGroupEdge(edge) ? LINK_GROUP_COLOR : LINK_DM_COLOR;
    },
    [contactParam],
  );

  const linkWidth = useCallback(
    (l: object) => {
      const edge = l as WxEdge;
      const mc = typeof edge.message_count === 'number' ? edge.message_count : 1;
      const base = Math.max(1, Math.log2(Math.max(1, mc)));
      if (contactParam) {
        const { src, tgt } = edgeEndpoints(edge);
        if (src === contactParam || tgt === contactParam) return base + 1.5;
      }
      return base;
    },
    [contactParam],
  );

  /* ------------------------------ 渲染 ------------------------------ */

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<MessageCircle size={36} />}
          title="微信关系分析"
          description="请先从顶部任务选择器选择一个包含微信数据的任务。"
        />
      </div>
    );
  }

  if (loading) return <div className="card"><LoadingBlock text="正在加载关系图…" /></div>;

  if (error) {
    return (
      <div className="card card-pad flex items-center gap-3 text-rose-600">
        <AlertTriangle size={18} />
        <span className="text-sm flex-1">关系图加载失败：{error}</span>
        <Button size="sm" onClick={() => void load()}>
          重试
        </Button>
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="card">
        <EmptyState icon={<MessageCircle size={36} />} title="未发现微信聊天记录" description="该任务未提取到微信数据库或聊天数据为空。" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        icon={MessageCircle}
        title="微信关系分析"
        subtitle={ownerInGraph && ownerId ? `机主：${nameById.get(ownerId) ?? ownerId}` : '聊天记录社交关系图谱'}
        actions={
          <Button size="sm" variant="ghost" onClick={() => void handleInvalidate()}>
            <RefreshCcw size={13} /> 重建缓存
          </Button>
        }
      />

      <StatsCards cards={statCards} />

      <div className="grid grid-cols-1 xl:grid-cols-[290px_minmax(0,1fr)_360px] gap-4 xl:h-[calc(100vh-17rem)] xl:min-h-[560px]">
        {/* 左栏：联系人清单 */}
        <ContactsPanel
          contacts={graph.nodes}
          ownerId={ownerInGraph ? ownerId : null}
          selectedId={contactParam || null}
          sort={sort === 'name' ? 'name' : 'msgs'}
          onSortChange={setSort}
          onSelect={handleSelectContact}
          loading={loading}
        />

        {/* 中栏：关系图谱 + 图例 */}
        <Card padded={false} className="overflow-hidden flex flex-col min-h-0">
          <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between gap-2 shrink-0">
            <h3 className="card-title flex items-center gap-1.5">
              社交关系图
              <Badge tone="accent">{graph.nodes.length} 节点</Badge>
              <Badge tone="neutral">{graph.links.length} 会话</Badge>
            </h3>
          </div>
          <div ref={wrapRef} className="flex-1 min-h-0">
            {size.width > 0 && (
              <ForceGraph2D
                ref={fgRef}
                graphData={graph as never}
                width={size.width}
                height={size.height}
                nodeLabel={nodeLabel}
                nodeColor={nodeColor}
                nodeVal={nodeVal}
                nodeRelSize={6}
                linkColor={linkColor}
                linkWidth={linkWidth}
                backgroundColor="transparent"
                onNodeClick={handleGraphNodeClick}
                onLinkClick={handleGraphLinkClick}
              />
            )}
          </div>
          <GraphLegend
            className="border-t border-ink-200 dark:border-ink-800 shrink-0"
            ownerPresent={ownerInGraph}
            contactCount={counts.contacts}
            groupNodeCount={counts.groups}
            dmEdgeCount={counts.dm}
            groupEdgeCount={counts.groupEdges}
          />
        </Card>

        {/* 右栏：会话记录 / 活跃趋势 */}
        <Card padded={false} className="flex flex-col min-h-0 overflow-hidden">
          <div className="px-3 py-2.5 border-b border-ink-200 dark:border-ink-800 shrink-0">
            <Segmented
              options={[
                { value: 'chat', label: '会话记录', icon: MessagesSquare },
                { value: 'trend', label: '活跃趋势', icon: BarChart3 },
              ]}
              value={wtab === 'trend' ? 'trend' : 'chat'}
              onChange={setWtab}
            />
          </div>
          {wtab === 'trend' ? (
            <TrendChartPanel trend={trend} />
          ) : selectedEdge && chatParam ? (
            <ChatRecordsPanel
              chatKey={chatParam}
              participants={edgeParticipants(selectedEdge)}
              messages={messages}
              loading={chatLoading}
              loadingMore={loadingMore}
              hasMore={hasMore}
              total={chatTotal}
              onLoadMore={() => void loadChat(selectedEdge, messages.length)}
              mtype={mtype}
              onMtypeChange={setMtype}
              onClear={() => setChatParam('')}
            />
          ) : (
            <EmptyState
              className="flex-1"
              icon={<MessagesSquare size={30} />}
              title="点击图谱连线查看会话"
              description="连线粗细代表消息量；在左侧点击联系人可查看详情并在图谱中定位。"
            />
          )}
        </Card>
      </div>

      <ContactDrawer
        taskId={taskId}
        node={drawerNode}
        onClose={() => setDrawerNode(null)}
        onLocate={(n) => centerOnNode(n.id)}
      />
    </div>
  );
}
