import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  Database,
  HardDrive,
  Brain,
  Minus,
  Server,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { getSystemHealth, getPythonHealth, getRedisStatus } from '../../../services/systemService';
import { getLLMStatus } from '../../../services/llmService';
import { getGraphitiStatus } from '../../../services/graphitiService';
import { useTranslation } from '../../../hooks/useTranslation';
import type { TranslationKey } from '../../../locales/keys';
import { cx } from '../../../lib/utils';

type ServiceState = 'online' | 'offline' | 'checking';
type LatencyTrend = 'up' | 'down' | 'flat';

interface ServiceHealth {
  /** Translation key of the service display name (system/service vocabulary). */
  labelKey: TranslationKey;
  Icon: LucideIcon;
  status: ServiceState;
  latency: number | null;
  /** Latency direction of this probing round vs the previous one. */
  trend?: LatencyTrend;
  /** Signed delta vs the previous round (ms); null when not comparable. */
  delta: number | null;
}

const INITIAL: Record<string, ServiceHealth> = {
  cpp: { labelKey: 'settings.service.cpp', Icon: Zap, status: 'checking', latency: null, delta: null },
  python: { labelKey: 'settings.service.python', Icon: Server, status: 'checking', latency: null, delta: null },
  neo4j: { labelKey: 'settings.service.neo4j', Icon: Database, status: 'checking', latency: null, delta: null },
  redis: { labelKey: 'settings.service.redis', Icon: HardDrive, status: 'checking', latency: null, delta: null },
  llm: { labelKey: 'settings.service.llm', Icon: Brain, status: 'checking', latency: null, delta: null },
};

/** Re-probe cadence — the trend arrows compare round-over-round. */
const PROBE_INTERVAL_MS = 30_000;

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

/** Round-over-round latency comparison; undefined trend when incomparable. */
function trendOf(
  prev: number | null,
  next: number | null,
): { trend?: LatencyTrend; delta: number | null } {
  if (prev == null || next == null) return { delta: null };
  if (next === prev) return { trend: 'flat', delta: 0 };
  return { trend: next > prev ? 'up' : 'down', delta: next - prev };
}

/**
 * Service health strip — probes all five backends on mount and re-probes on
 * a fixed cadence, showing a ↑/↓ latency delta against the previous round.
 */
export default function ServiceHealthStrip() {
  const { t } = useTranslation();
  const [services, setServices] = useState(INITIAL);
  // Mirror for the probe callback so a new round can snapshot latencies
  // without depending on state that would re-trigger the effect.
  const servicesRef = useRef(services);
  servicesRef.current = services;
  const prevLatencyRef = useRef<Record<string, number | null>>({});

  const runProbes = useCallback(() => {
    // Freeze current latencies as this round's baseline before overwriting.
    prevLatencyRef.current = Object.fromEntries(
      Object.entries(servicesRef.current).map(([key, svc]) => [key, svc.latency]),
    );

    const patch = (key: string, result: { status: ServiceState; latency: number | null }) => {
      const { trend, delta } = trendOf(prevLatencyRef.current[key] ?? null, result.latency);
      setServices((prev) => ({ ...prev, [key]: { ...prev[key], ...result, trend, delta } }));
    };

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

  useEffect(() => {
    void runProbes();
    const id = setInterval(() => void runProbes(), PROBE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [runProbes]);

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
          <p className="text-xs font-medium text-ink-700 dark:text-ink-300 truncate">{t(svc.labelKey)}</p>
          <p
            className={cx(
              'mt-0.5 text-2xs',
              svc.status === 'online' && 'text-emerald-600 dark:text-emerald-400',
              svc.status === 'checking' && 'text-amber-600 dark:text-amber-400',
              svc.status === 'offline' && 'text-rose-600 dark:text-rose-400',
            )}
          >
            {svc.status === 'online' ? t('system.online') : svc.status === 'checking' ? t('system.checking') : t('system.offline')}
            {svc.latency != null && (
              <span className="ml-1.5 font-mono text-ink-400">{svc.latency}ms</span>
            )}
          </p>
          {svc.trend && (
            <p
              className={cx(
                'mt-1 flex items-center gap-0.5 text-2xs font-medium',
                svc.trend === 'up' && 'text-rose-600 dark:text-rose-400',
                svc.trend === 'down' && 'text-emerald-600 dark:text-emerald-400',
                svc.trend === 'flat' && 'text-ink-400 dark:text-ink-500',
              )}
            >
              {svc.trend === 'up' && <ArrowUp size={10} />}
              {svc.trend === 'down' && <ArrowDown size={10} />}
              {svc.trend === 'flat' && <Minus size={10} />}
              {svc.trend === 'flat'
                ? t('dashboard.health.trend_flat')
                : t('dashboard.health.trend_delta').replace(
                    '{delta}',
                    `${svc.delta != null && svc.delta > 0 ? '+' : ''}${svc.delta}`,
                  )}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
