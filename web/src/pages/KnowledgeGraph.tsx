import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  AlertTriangle,
  Boxes,
  GitBranch,
  Network,
  RefreshCcw,
  Search as SearchIcon,
  UploadCloud,
} from 'lucide-react';
import {
  searchGraph,
  listEntities,
  listRelationships,
  getGraphitiStatus,
  ingestTaskData,
  reingestAnalyzedData,
  getGraphData,
} from '../services/graphitiService';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { cx, errorMessage } from '../lib/utils';
import { PageHeader } from '../components/ui/PageScaffold';
import { useUrlState } from '../hooks/useUrlState';
import { useAppSelector } from '../store';
import { downloadJSON } from '../lib/exportUtils';
import { useElementSize } from '../components/graph/useElementSize';
import GraphStatsBar from './knowledgegraph/GraphStatsBar';
import NodeSearchPanel from './knowledgegraph/NodeSearchPanel';
import GraphControls from './knowledgegraph/GraphControls';
import GraphLegend from './knowledgegraph/GraphLegend';
import NodeDrawer, { type NodeRelationItem } from './knowledgegraph/NodeDrawer';
import {
  CANVAS_DARK,
  CANVAS_LIGHT,
  FOCUS_RING,
  MATCH_RING,
  buildTypeStats,
  computeDegrees,
  endpointId,
  exportGraphCanvasPng,
  filterGraph,
  linkKey,
  linkType,
  matchNode,
  nodeName,
  nodeRadius,
  serializeGraph,
  typeMeta,
  type KgGraph,
  type KgLink,
  type KgNode,
} from './knowledgegraph/kgUtils';

type KgTab = 'graph' | 'search' | 'entities' | 'relationships';

const KG_TABS: KgTab[] = ['graph', 'search', 'entities', 'relationships'];

export default function KnowledgeGraph() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();
  const theme = useAppSelector((state) => state.settings.theme);
  const isDark = theme === 'dark';
  const pal = isDark ? CANVAS_DARK : CANVAS_LIGHT;

  // URL 持久化：页签 / 类型过滤 / 关系数阈值 / 当前定位节点。
  const [tabParam, setTabParam] = useUrlState('tab', 'graph');
  const [typesParam, setTypesParam] = useUrlState('etypes', '');
  const [degParam, setDegParam] = useUrlState('mdeg', '0');
  const [focusParam, setFocusParam] = useUrlState('fnode', '');

  const activeTab: KgTab = KG_TABS.includes(tabParam as KgTab) ? (tabParam as KgTab) : 'graph';

  const [connected, setConnected] = useState<boolean | null>(null);
  const [graph, setGraph] = useState<KgGraph>({ nodes: [], links: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Record<string, unknown>[]>([]);
  const [searching, setSearching] = useState(false);

  const [entities, setEntities] = useState<Record<string, unknown>[]>([]);
  const [relationships, setRelationships] = useState<Record<string, unknown>[]>([]);

  // 图谱视图本地状态：节点搜索词 / 详情抽屉 / 选中边 / 冷却状态 / 导出中。
  const [nodeQuery, setNodeQuery] = useState('');
  const [drawerNode, setDrawerNode] = useState<KgNode | null>(null);
  const [selectedLinkKey, setSelectedLinkKey] = useState('');
  const [cooling, setCooling] = useState(false);
  const [exporting, setExporting] = useState(false);

  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const { ref: observeWrap, size } = useElementSize<HTMLDivElement>();
  const wrapDomRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<KgGraph>({ nodes: [], links: [] });
  const timerRef = useRef<number | null>(null);
  const didFitRef = useRef(false);
  const didAutoCenterRef = useRef(false);

  // 容器同时承担 ResizeObserver 观测与 PNG 导出时的画布查找。
  const wrapRefCb = useCallback(
    (el: HTMLDivElement | null) => {
      wrapDomRef.current = el;
      observeWrap(el);
    },
    [observeWrap],
  );

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

  useEffect(() => {
    if (!taskId) return;
    getGraphitiStatus(taskId)
      .then((s) => setConnected(Boolean((s as { neo4j_connected?: boolean })?.neo4j_connected)))
      .catch(() => setConnected(false));
  }, [taskId]);

  const loadGraph = useCallback(async () => {
    if (!taskId) return;
    setGraphLoading(true);
    setGraphError(null);
    try {
      const data = (await getGraphData(taskId, 200)) as { nodes?: KgNode[]; links?: KgLink[] };
      setGraph({ nodes: data?.nodes ?? [], links: data?.links ?? [] });
      didFitRef.current = false;
      didAutoCenterRef.current = false;
      setCooling(true);
    } catch (err) {
      const msg = errorMessage(err);
      setGraphError(msg);
      toast.error(`图谱加载失败：${msg}`);
    } finally {
      setGraphLoading(false);
    }
  }, [taskId, toast]);

  useEffect(() => {
    if (activeTab === 'graph' && taskId && graph.nodes.length === 0 && !graphLoading && !graphError) {
      void loadGraph();
    }
  }, [activeTab, taskId, graph.nodes.length, graphLoading, graphError, loadGraph]);

  useEffect(() => {
    if (!taskId) return;
    if (activeTab === 'entities') {
      listEntities(taskId)
        .then((d) => setEntities(((d as { entities?: Record<string, unknown>[] })?.entities ?? []) as Record<string, unknown>[]))
        .catch(() => setEntities([]));
    }
    if (activeTab === 'relationships') {
      listRelationships(taskId)
        .then((d) => setRelationships(((d as { relationships?: Record<string, unknown>[] })?.relationships ?? []) as Record<string, unknown>[]))
        .catch(() => setRelationships([]));
    }
  }, [activeTab, taskId]);

  const handleSearch = async () => {
    if (!taskId || !searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = (await searchGraph(searchQuery.trim(), taskId)) as { results?: Record<string, unknown>[] };
      setSearchResults(res?.results ?? []);
    } catch (err) {
      toast.error(`搜索失败：${errorMessage(err)}`);
    } finally {
      setSearching(false);
    }
  };

  const handleIngest = async (analyzedOnly: boolean) => {
    if (!taskId) return;
    setIngesting(true);
    try {
      if (analyzedOnly) await reingestAnalyzedData(taskId);
      else await ingestTaskData(taskId);
      toast.success('导入任务已启动');
    } catch (err) {
      toast.error(`导入失败：${errorMessage(err)}`);
    } finally {
      setIngesting(false);
    }
  };

  /* ------------------------------ 派生数据 ------------------------------ */

  const minDegree = Math.max(0, Math.floor(Number(degParam)) || 0);
  const setMinDegree = useCallback((v: number) => setDegParam(String(v)), [setDegParam]);

  const activeTypes = useMemo(
    () => typesParam.split(',').map((s) => s.trim()).filter(Boolean),
    [typesParam],
  );

  const toggleType = useCallback(
    (key: string) => {
      const next = activeTypes.includes(key)
        ? activeTypes.filter((k) => k !== key)
        : [...activeTypes, key];
      setTypesParam(next.join(','));
    },
    [activeTypes, setTypesParam],
  );

  const degrees = useMemo(() => computeDegrees(graph.links), [graph.links]);

  const maxDegree = useMemo(() => {
    let m = 0;
    degrees.forEach((v) => {
      if (v > m) m = v;
    });
    return m;
  }, [degrees]);

  const typeStats = useMemo(() => buildTypeStats(graph.nodes), [graph.nodes]);

  const visibleGraph = useMemo(
    () => filterGraph(graph, activeTypes, minDegree, degrees),
    [graph, activeTypes, minDegree, degrees],
  );

  const nodeById = useMemo(() => {
    const m = new Map<string, KgNode>();
    graph.nodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [graph.nodes]);

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    graph.nodes.forEach((n) => m.set(n.id, nodeName(n)));
    return m;
  }, [graph.nodes]);

  // 搜索命中集合：null 表示未在搜索（不做高亮/压暗）。
  const matchIds = useMemo(() => {
    if (!nodeQuery.trim()) return null;
    const s = new Set<string>();
    visibleGraph.nodes.forEach((n) => {
      if (matchNode(n, nodeQuery)) s.add(n.id);
    });
    return s;
  }, [visibleGraph.nodes, nodeQuery]);

  const drawerRelations = useMemo<NodeRelationItem[]>(() => {
    if (!drawerNode) return [];
    const items: NodeRelationItem[] = [];
    graph.links.forEach((l) => {
      const s = endpointId(l.source);
      const t = endpointId(l.target);
      if (s === drawerNode.id) items.push({ link: l, otherId: t, direction: 'out' });
      else if (t === drawerNode.id) items.push({ link: l, otherId: s, direction: 'in' });
    });
    return items.slice(0, 200);
  }, [drawerNode, graph.links]);

  /* ------------------------------ 图谱交互 ------------------------------ */

  const centerOnNode = useCallback((id: string, attempts = 10) => {
    const node = graphRef.current.nodes.find((n) => n.id === id) as
      | (KgNode & { x?: number; y?: number })
      | undefined;
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

  const handleSearchSelect = useCallback(
    (node: KgNode) => {
      setFocusParam(node.id);
      setDrawerNode(node);
      centerOnNode(node.id);
    },
    [setFocusParam, centerOnNode],
  );

  const handleGraphNodeClick = useCallback(
    (n: object) => {
      const node = n as KgNode;
      if (!node.id) return;
      setFocusParam(node.id);
      setDrawerNode(node);
    },
    [setFocusParam],
  );

  const handleGraphLinkClick = useCallback(
    (l: object) => {
      const link = l as KgLink;
      const s = endpointId(link.source);
      const t = endpointId(link.target);
      setSelectedLinkKey(linkKey(link));
      toast.info(`关系：${nameById.get(s) ?? s} → ${nameById.get(t) ?? t}（${linkType(link)}）`);
    },
    [nameById, toast],
  );

  const handleEngineStop = useCallback(() => {
    setCooling(false);
    // 首次布局收敛后整体缩放适配一次。
    if (!didFitRef.current && graphRef.current.nodes.length > 0) {
      didFitRef.current = true;
      fgRef.current?.zoomToFit(400, 40);
    }
  }, []);

  const handleReheat = useCallback(() => {
    fgRef.current?.d3ReheatSimulation();
    setCooling(true);
  }, []);

  const handleZoomStep = useCallback((factor: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    const next = Math.max(0.15, Math.min(8, fg.zoom() * factor));
    fg.zoom(next, 220);
  }, []);

  const handleFit = useCallback(() => {
    fgRef.current?.zoomToFit(400, 40);
  }, []);

  // 带定位参数进入页面（或刷新）时，图谱就绪后自动定位一次。
  useEffect(() => {
    if (!didAutoCenterRef.current && graph.nodes.length > 0 && focusParam) {
      didAutoCenterRef.current = true;
      centerOnNode(focusParam);
    }
  }, [graph.nodes.length, focusParam, centerOnNode]);

  const handleExportPng = useCallback(() => {
    if (!taskId) return;
    setExporting(true);
    try {
      const ok = exportGraphCanvasPng(wrapDomRef.current, taskId, isDark);
      if (ok) {
        toast.success(`已导出图谱 PNG：graph-${taskId.slice(0, 8)}.png`);
      } else {
        // 画布不可用时（如尚未渲染）降级导出结构化数据，并如实提示。
        downloadJSON(serializeGraph(graphRef.current), `graph-${taskId.slice(0, 8)}.json`);
        toast.info('未找到可导出的画布，已改为导出节点/边 JSON 数据');
      }
    } finally {
      setExporting(false);
    }
  }, [taskId, isDark, toast]);

  /* ------------------------------ 画布绘制 ------------------------------ */

  const nodeLabel = useCallback((n: object) => nodeName(n as KgNode), []);

  const paintNode = useCallback(
    (obj: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const node = obj as KgNode & { x?: number; y?: number };
      if (typeof node.x !== 'number' || typeof node.y !== 'number') return;
      const meta = typeMeta(node.type);
      const isMatch = matchIds?.has(node.id) ?? false;
      const dimmed = matchIds !== null && !isMatch;
      const isFocus = node.id === focusParam;
      const r = nodeRadius(node, degrees);

      ctx.globalAlpha = dimmed ? 0.15 : 1;

      // 命中/定位节点的强调环。
      if (isFocus || isMatch) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 3 / globalScale, 0, 2 * Math.PI);
        ctx.lineWidth = (isFocus ? 2 : 1.5) / globalScale;
        ctx.strokeStyle = isFocus ? FOCUS_RING : MATCH_RING;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = meta.color;
      ctx.fill();

      if (!dimmed && globalScale > 0.6) {
        const label = nodeName(node);
        if (label) {
          const fontSize = 11 / globalScale;
          ctx.font = `${fontSize}px "Inter Variable", "PingFang SC", "Microsoft YaHei", sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          ctx.lineWidth = 3 / globalScale;
          ctx.strokeStyle = pal.halo;
          ctx.strokeText(label, node.x, node.y + r + 2 / globalScale);
          ctx.fillStyle = pal.text;
          ctx.fillText(label, node.x, node.y + r + 2 / globalScale);
        }
      }
      ctx.globalAlpha = 1;
    },
    [matchIds, focusParam, degrees, pal],
  );

  // 命中检测区域与自定义绘制半径保持一致。
  const paintPointerArea = useCallback(
    (obj: object, _paintColor: string, ctx: CanvasRenderingContext2D) => {
      const node = obj as KgNode & { x?: number; y?: number };
      if (typeof node.x !== 'number' || typeof node.y !== 'number') return;
      ctx.beginPath();
      ctx.arc(node.x, node.y, nodeRadius(node, degrees) + 2, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(0,0,0,1)';
      ctx.fill();
    },
    [degrees],
  );

  const linkColorFn = useCallback(
    (l: object) => {
      const link = l as KgLink;
      const s = endpointId(link.source);
      const t = endpointId(link.target);
      if (selectedLinkKey && linkKey(link) === selectedLinkKey) return pal.linkFocus;
      if (focusParam && (s === focusParam || t === focusParam)) return pal.linkFocus;
      if (matchIds !== null && (!matchIds.has(s) || !matchIds.has(t))) return pal.linkDim;
      return pal.link;
    },
    [selectedLinkKey, focusParam, matchIds, pal],
  );

  const linkWidthFn = useCallback(
    (l: object) => {
      const link = l as KgLink;
      const s = endpointId(link.source);
      const t = endpointId(link.target);
      if (selectedLinkKey && linkKey(link) === selectedLinkKey) return 2.5;
      if (focusParam && (s === focusParam || t === focusParam)) return 2;
      return 1;
    },
    [selectedLinkKey, focusParam],
  );

  /* ------------------------------ 渲染 ------------------------------ */

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<Network size={36} />} title="未选择任务" description="请选择一个任务查看其知识图谱。" />
      </div>
    );
  }

  const TABS: { key: KgTab; label: string; Icon: typeof Network }[] = [
    { key: 'graph', label: '图谱', Icon: Network },
    { key: 'search', label: '搜索', Icon: SearchIcon },
    { key: 'entities', label: '实体', Icon: Boxes },
    { key: 'relationships', label: '关系', Icon: GitBranch },
  ];

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader icon={Network} tone="sky" title="知识图谱" subtitle="证据实体与关系的图谱可视化" />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
          {TABS.map(({ key, label, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTabParam(key)}
              className={cx(
                'px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-colors',
                activeTab === key
                  ? 'bg-accent-600 text-white'
                  : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className={cx('chip', connected ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20' : 'bg-ink-100 text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-400 dark:border-ink-700')}>
            Neo4j {connected === null ? '检测中' : connected ? '已连接' : '离线'}
          </span>
          <Button size="sm" onClick={() => void handleIngest(true)} disabled={ingesting}>
            <RefreshCcw size={13} /> 增量导入
          </Button>
          <Button size="sm" onClick={() => void handleIngest(false)} disabled={ingesting}>
            <UploadCloud size={13} /> {ingesting ? '导入中…' : '全量导入'}
          </Button>
        </div>
      </div>

      {activeTab === 'graph' && (
        <div className="space-y-4">
          <GraphStatsBar
            nodeTotal={graph.nodes.length}
            linkTotal={graph.links.length}
            typeStats={typeStats}
            activeTypes={activeTypes}
            onToggleType={toggleType}
          />
          <Card padded={false} className="overflow-hidden flex flex-col h-[calc(100vh-24rem)] min-h-[560px]">
            <div className="px-3 py-2 border-b border-ink-200 dark:border-ink-800 flex flex-wrap items-center gap-2 shrink-0">
              <NodeSearchPanel
                nodes={visibleGraph.nodes}
                value={nodeQuery}
                onChange={setNodeQuery}
                onSelect={handleSearchSelect}
              />
              <div className="ml-auto">
                <GraphControls
                  cooling={cooling}
                  minDegree={minDegree}
                  maxDegree={maxDegree}
                  onMinDegreeChange={setMinDegree}
                  onZoomIn={() => handleZoomStep(1.35)}
                  onZoomOut={() => handleZoomStep(1 / 1.35)}
                  onFit={handleFit}
                  onReheat={handleReheat}
                  onExportPng={handleExportPng}
                  exporting={exporting}
                />
              </div>
            </div>
            {graphLoading ? (
              <LoadingBlock text="正在加载图谱…" />
            ) : graphError ? (
              <div className="flex-1 flex items-center justify-center px-4">
                <div className="flex items-center gap-3 text-rose-600 dark:text-rose-400">
                  <AlertTriangle size={18} className="shrink-0" />
                  <span className="text-sm">图谱加载失败：{graphError}</span>
                  <Button size="sm" onClick={() => void loadGraph()}>
                    重试
                  </Button>
                </div>
              </div>
            ) : graph.nodes.length === 0 ? (
              <EmptyState
                icon={<Network size={36} />}
                title="图谱为空"
                description="该任务还没有知识图谱数据。可先执行全量导入把任务数据写入图谱，或前往分析中心生成实体与关系后增量导入。"
                action={
                  <Button variant="primary" size="sm" onClick={() => void handleIngest(false)} disabled={ingesting}>
                    <UploadCloud size={13} /> {ingesting ? '导入中…' : '全量导入任务数据'}
                  </Button>
                }
              />
            ) : (
              <div ref={wrapRefCb} className="flex-1 min-h-0 relative">
                {size.width > 0 && size.height > 0 && (
                  <ForceGraph2D
                    ref={fgRef}
                    graphData={visibleGraph as never}
                    width={size.width}
                    height={size.height}
                    nodeLabel={nodeLabel}
                    nodeCanvasObject={paintNode}
                    nodeCanvasObjectMode={() => 'replace'}
                    nodePointerAreaPaint={paintPointerArea}
                    linkColor={linkColorFn}
                    linkWidth={linkWidthFn}
                    linkHoverPrecision={4}
                    linkDirectionalArrowLength={3.5}
                    linkDirectionalArrowRelPos={1}
                    backgroundColor="transparent"
                    onNodeClick={handleGraphNodeClick}
                    onLinkClick={handleGraphLinkClick}
                    onEngineStop={handleEngineStop}
                  />
                )}
                {matchIds !== null && (
                  <span className="absolute left-3 top-2.5 chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
                    命中 {matchIds.size} 个节点
                  </span>
                )}
                {visibleGraph.nodes.length === 0 && (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/70 dark:bg-ink-950/60 pointer-events-none">
                    <p className="text-xs text-ink-500 dark:text-ink-400 px-6 text-center">
                      当前过滤条件下没有可见节点，请降低关系数阈值或清除类型过滤。
                    </p>
                  </div>
                )}
              </div>
            )}
            {graph.nodes.length > 0 && (
              <GraphLegend className="border-t border-ink-200 dark:border-ink-800 shrink-0" typeStats={typeStats} />
            )}
          </Card>
        </div>
      )}

      {activeTab === 'search' && (
        <Card>
          <CardHeader title="图谱搜索" subtitle="基于 Graphiti 的语义搜索，与画布内的即时节点搜索相互独立" />
          <div className="flex gap-2 mb-4">
            <input
              type="text"
              className="input flex-1"
              placeholder="输入实体名称或关键词…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleSearch()}
            />
            <Button variant="primary" onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
              <SearchIcon size={14} /> {searching ? '搜索中…' : '搜索'}
            </Button>
          </div>
          {searchResults.length === 0 ? (
            <EmptyState title="无结果" />
          ) : (
            <ul className="divide-y divide-ink-100 dark:divide-ink-800">
              {searchResults.map((r, i) => (
                <li key={i} className="py-2.5 text-xs">
                  <p className="font-medium text-ink-800 dark:text-ink-100">{String(r.name ?? r.id ?? '—')}</p>
                  {r.summary != null && (
                    <p className="text-ink-500 dark:text-ink-400 mt-0.5 line-clamp-2">{String(r.summary)}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {(activeTab === 'entities' || activeTab === 'relationships') && (
        <Card padded={false}>
          {(() => {
            const rows = activeTab === 'entities' ? entities : relationships;
            if (rows.length === 0) return <EmptyState title="暂无数据" />;
            const keys = Object.keys(rows[0]).slice(0, 5);
            return (
              <div className="overflow-x-auto">
                <table className="table-shell">
                  <thead>
                    <tr>{keys.map((k) => <th key={k}>{k}</th>)}</tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 200).map((row, i) => (
                      <tr key={i}>
                        {keys.map((k) => (
                          <td key={k} className="text-xs max-w-[220px] truncate">
                            {String(row[k] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}
        </Card>
      )}

      <NodeDrawer
        node={drawerNode}
        relations={drawerRelations}
        nodeById={nodeById}
        degree={drawerNode ? degrees.get(drawerNode.id) ?? 0 : 0}
        onClose={() => setDrawerNode(null)}
        onLocate={(n) => centerOnNode(n.id)}
        onOpenNode={(n) => {
          setDrawerNode(n);
          setFocusParam(n.id);
          centerOnNode(n.id);
        }}
      />
    </div>
  );
}
