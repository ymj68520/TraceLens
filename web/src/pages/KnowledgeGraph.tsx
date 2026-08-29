import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { Network, Search as SearchIcon, Boxes, GitBranch, UploadCloud, RefreshCcw } from 'lucide-react';
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

type KgTab = 'graph' | 'search' | 'entities' | 'relationships';

interface GraphNode {
  id: string;
  name?: string;
  type?: string;
  [key: string]: unknown;
}

interface GraphLink {
  source: string;
  target: string;
  type?: string;
  [key: string]: unknown;
}

const NODE_COLORS: Record<string, string> = {
  file: '#2e9b96',
  person: '#4f83cc',
  process: '#d45b6a',
  network: '#c98f2e',
  default: '#8b9da2',
};

const nodeColor = (type?: string) => NODE_COLORS[type ?? ''] ?? NODE_COLORS.default;

export default function KnowledgeGraph() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  const [activeTab, setActiveTab] = useState<KgTab>('graph');
  const [connected, setConnected] = useState<boolean | null>(null);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({ nodes: [], links: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const graphRef = useRef<HTMLDivElement>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Record<string, unknown>[]>([]);
  const [searching, setSearching] = useState(false);

  const [entities, setEntities] = useState<Record<string, unknown>[]>([]);
  const [relationships, setRelationships] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    if (!taskId) return;
    getGraphitiStatus(taskId)
      .then((s) => setConnected(Boolean((s as { neo4j_connected?: boolean })?.neo4j_connected)))
      .catch(() => setConnected(false));
  }, [taskId]);

  const loadGraph = useCallback(async () => {
    if (!taskId) return;
    setGraphLoading(true);
    try {
      const data = (await getGraphData(taskId, 200)) as { nodes?: GraphNode[]; links?: GraphLink[] };
      setGraph({ nodes: data?.nodes ?? [], links: data?.links ?? [] });
    } catch (err) {
      toast.error(`图谱加载失败：${errorMessage(err)}`);
    } finally {
      setGraphLoading(false);
    }
  }, [taskId, toast]);

  useEffect(() => {
    if (activeTab === 'graph' && taskId && graph.nodes.length === 0) void loadGraph();
  }, [activeTab, taskId, graph.nodes.length, loadGraph]);

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
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
          {TABS.map(({ key, label, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
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
          <Button size="sm" onClick={() => handleIngest(true)} disabled={ingesting}>
            <RefreshCcw size={13} /> 增量导入
          </Button>
          <Button size="sm" onClick={() => handleIngest(false)} disabled={ingesting}>
            <UploadCloud size={13} /> {ingesting ? '导入中…' : '全量导入'}
          </Button>
        </div>
      </div>

      {activeTab === 'graph' && (
        <Card padded={false} className="overflow-hidden">
          {graphLoading ? (
            <LoadingBlock text="正在加载图谱…" />
          ) : graph.nodes.length === 0 ? (
            <EmptyState title="图谱为空" description="先执行全量导入，将任务数据写入 Neo4j。" />
          ) : (
            <div ref={graphRef} style={{ height: 560 }}>
              <ForceGraph2D
                graphData={graph as never}
                width={graphRef.current?.clientWidth || 900}
                height={560}
                nodeLabel={(n) => String((n as GraphNode).name ?? (n as GraphNode).id)}
                nodeColor={(n) => nodeColor((n as GraphNode).type)}
                nodeRelSize={5}
                linkWidth={1}
                linkColor={() => '#b4c0c3'}
                backgroundColor="transparent"
              />
            </div>
          )}
        </Card>
      )}

      {activeTab === 'search' && (
        <Card>
          <CardHeader title="图谱搜索" />
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
    </div>
  );
}
