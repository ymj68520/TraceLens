import { useEffect, useState } from 'react';
import { Database, HardDrive, Brain, Server, Zap, type LucideIcon } from 'lucide-react';
import { getSystemHealth, getPythonHealth, getRedisStatus } from '../../../services/systemService';
import { getLLMStatus } from '../../../services/llmService';
import { getGraphitiStatus } from '../../../services/graphitiService';
import { cx } from '../../../lib/utils';

type ServiceState = 'online' | 'offline' | 'checking';

interface ServiceHealth {
  label: string;
  Icon: LucideIcon;
  status: ServiceState;
  latency: number | null;
}

const INITIAL: Record<string, ServiceHealth> = {
  cpp: { label: 'C++ 后端', Icon: Zap, status: 'checking', latency: null },
  python: { label: 'Python 服务', Icon: Server, status: 'checking', latency: null },
  neo4j: { label: 'Neo4j 图数据库', Icon: Database, status: 'checking', latency: null },
  redis: { label: 'Redis 缓存', Icon: HardDrive, status: 'checking', latency: null },
  llm: { label: 'LLM 服务', Icon: Brain, status: 'checking', latency: null },
};

async function probe<T>(fn: () => Promise<T>, ok: (result: T) => boolean = () => true) {
  const start = Date.now();
  try {
    const result = await fn();
    return ok(result)
      ? { status: 'online' as const, latency: Date.now() - start }
      : { status: 'offline' as const, latency: Date.now() - start };
  } catch {
    return { status: 'offline' as const, latency: null };
  }
}

/** Service health strip — probes all five backends once on mount. */
export default function ServiceHealthStrip() {
  const [services, setServices] = useState(INITIAL);

  useEffect(() => {
    const patch = (key: string, result: { status: ServiceState; latency: number | null }) =>
      setServices((prev) => ({ ...prev, [key]: { ...prev[key], ...result } }));

    void probe(getSystemHealth).then((r) => patch('cpp', r));
    void probe(getPythonHealth).then((r) => patch('python', r));
    void probe(getGraphitiStatus, (s) => Boolean((s as { neo4j_connected?: boolean })?.neo4j_connected)).then(
      (r) => patch('neo4j', r),
    );
    void probe(getRedisStatus, (s) => Boolean((s as { connected?: boolean })?.connected)).then((r) =>
      patch('redis', r),
    );
    void probe(getLLMStatus, (s) => {
      const st = (s as { status?: string })?.status;
      return st === 'available' || st === 'healthy';
    }).then((r) => patch('llm', r));
  }, []);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      {Object.entries(services).map(([key, svc]) => (
        <div key={key} className="card px-4 py-3.5">
          <div className="flex items-center justify-between mb-2">
            <svc.Icon size={16} className="text-ink-400 dark:text-ink-500" />
            <span
              className={cx(
                svc.status === 'online' && 'dot-ok',
                svc.status === 'checking' && 'dot-warn animate-pulse',
                svc.status === 'offline' && 'dot-err',
              )}
            />
          </div>
          <p className="text-xs font-medium text-ink-700 dark:text-ink-300 truncate">{svc.label}</p>
          <p
            className={cx(
              'mt-0.5 text-2xs',
              svc.status === 'online' && 'text-emerald-600 dark:text-emerald-400',
              svc.status === 'checking' && 'text-amber-600 dark:text-amber-400',
              svc.status === 'offline' && 'text-rose-600 dark:text-rose-400',
            )}
          >
            {svc.status === 'online' ? '在线' : svc.status === 'checking' ? '检测中…' : '离线'}
            {svc.latency != null && (
              <span className="ml-1.5 font-mono text-ink-400">{svc.latency}ms</span>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}
