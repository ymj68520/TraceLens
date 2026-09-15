import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { LogIn, LogOut, RefreshCw, Server, Wifi, WifiOff } from 'lucide-react';
import { csLogin, listClients } from '../services/csService';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { PageHeader, SkeletonBlock, StatStrip } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import { useAppSelector } from '../store';
import { useTranslation } from '../hooks/useTranslation';
import { cx, errorMessage, formatRelativeTime } from '../lib/utils';

/* ---------------------------------------------------------------------------
 * 分布式节点页：登录 :8091 C/S 服务后拉取已注册采集节点，卡片化展示。
 * 接入 = csLogin（OAuth2 密码流，token 存 cs_auth_token）；
 * 断开 = 清除本地 token。轮询走真实 listClients 接口。
 * ------------------------------------------------------------------------- */

interface ClientNode {
  id: string;
  name: string;
  address: string | null;
  rawStatus: string;
  /** online / offline / unknown 三态，由原始 status 归一化而来 */
  status: 'online' | 'offline' | 'unknown';
  latencyMs: number | null;
  roles: string[];
  lastSeen: string | null;
  version: string | null;
}

const ONLINE_SET = new Set(['online', 'connected', 'active', 'idle']);
const OFFLINE_SET = new Set(['offline', 'disconnected', 'lost', 'down', 'unreachable']);

const asRecord = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

const pickStr = (rec: Record<string, unknown>, keys: string[]): string | null => {
  for (const k of keys) {
    const v = rec[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
    if (typeof v === 'number') return String(v);
  }
  return null;
};

const pickRoles = (rec: Record<string, unknown>): string[] => {
  const out: string[] = [];
  const push = (v: unknown) => {
    if (typeof v === 'string' && v.trim()) out.push(v.trim());
  };
  for (const k of ['roles', 'tags', 'capabilities', 'labels']) {
    const v = rec[k];
    if (Array.isArray(v)) v.forEach(push);
    else if (typeof v === 'string') push(v);
  }
  push(rec.role);
  return [...new Set(out)].slice(0, 4);
};

/**
 * listClients 的响应结构没有前端契约，按常见包装层做宽容解析；
 * 解析不出的字段一律留空展示为「—」，不做任何臆造。
 */
const normalizeClients = (payload: unknown): ClientNode[] => {
  const rec = asRecord(payload);
  const list: unknown[] = Array.isArray(payload)
    ? payload
    : rec && Array.isArray(rec.clients)
      ? rec.clients
      : rec && Array.isArray(rec.items)
        ? rec.items
        : rec && Array.isArray(rec.data)
          ? rec.data
          : rec && Array.isArray(rec.results)
            ? rec.results
            : [];

  return list.map((raw, idx) => {
    const c = asRecord(raw);
    const id = (c && pickStr(c, ['client_id', 'id', 'uuid', 'node_id'])) ?? `node-${idx}`;
    const rawStatus = ((c && pickStr(c, ['status', 'state'])) ?? 'unknown').toLowerCase();
    const latencyRaw = c ? (c.latency_ms ?? c.latency ?? c.rtt_ms ?? c.rtt) : undefined;
    return {
      id,
      name: (c && pickStr(c, ['hostname', 'name', 'client_name', 'node_name'])) ?? id,
      address: c ? pickStr(c, ['address', 'addr', 'endpoint', 'url', 'host', 'ip']) : null,
      rawStatus,
      status: ONLINE_SET.has(rawStatus) ? 'online' : OFFLINE_SET.has(rawStatus) ? 'offline' : 'unknown',
      latencyMs: typeof latencyRaw === 'number' && latencyRaw >= 0 ? latencyRaw : null,
      roles: c ? pickRoles(c) : [],
      lastSeen: c ? pickStr(c, ['last_seen', 'last_seen_at', 'last_heartbeat', 'updated_at']) : null,
      version: c ? pickStr(c, ['version', 'agent_version', 'client_version']) : null,
    };
  });
};

export default function Distributed() {
  const toast = useToast();
  const { t } = useTranslation();
  const refreshInterval = useAppSelector((state) => state.settings.refreshInterval);

  const [username, setUsername] = useState('super_admin');
  const [password, setPassword] = useState('admin123');
  const [connecting, setConnecting] = useState(false);
  const [hasToken, setHasToken] = useState(() => Boolean(localStorage.getItem('cs_auth_token')));

  const [clients, setClients] = useState<ClientNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [rawPayload, setRawPayload] = useState<unknown>(null);

  const loadClients = useCallback(async (opts?: { silent?: boolean }): Promise<boolean> => {
    if (!localStorage.getItem('cs_auth_token')) {
      setClients(null);
      setRawPayload(null);
      return false;
    }
    if (!opts?.silent) setLoading(true);
    try {
      const resp = await listClients();
      setClients(normalizeClients(resp));
      setRawPayload(resp);
      setListError(null);
      return true;
    } catch (err) {
      setListError(errorMessage(err));
      // 401 时拦截器已清除失效 token，同步 UI 回到未接入状态
      if ((err as { status?: number } | null)?.status === 401) {
        setHasToken(false);
        setClients(null);
      }
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (hasToken) void loadClients();
  }, [hasToken, loadClients]);

  /* 自动刷新：复用全局刷新间隔（下限 3s），仅静默轮询，不打扰 */
  useEffect(() => {
    if (!autoRefresh || !hasToken) return;
    const id = window.setInterval(() => void loadClients({ silent: true }), Math.max(3000, refreshInterval));
    return () => window.clearInterval(id);
  }, [autoRefresh, hasToken, refreshInterval, loadClients]);

  const handleConnect = async (e: FormEvent) => {
    e.preventDefault();
    setConnecting(true);
    try {
      const resp = (await csLogin(username, password)) as { access_token?: string };
      const token = resp?.access_token;
      if (!token) throw new Error(t('distributed.error.token_missing'));
      localStorage.setItem('cs_auth_token', token);
      setHasToken(true);
      toast.success(t('distributed.toast.connected'));
    } catch (err) {
      toast.error(t('distributed.toast.connect_failed').replace('{error}', errorMessage(err)));
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = () => {
    localStorage.removeItem('cs_auth_token');
    setHasToken(false);
    setClients(null);
    setRawPayload(null);
    setListError(null);
    setAutoRefresh(false);
    toast.info(t('distributed.toast.disconnected'));
  };

  const handleRefresh = async () => {
    const ok = await loadClients();
    if (ok) toast.success(t('distributed.toast.refreshed'));
    else toast.error(t('distributed.toast.refresh_failed'));
  };

  const onlineCount = clients?.filter((c) => c.status === 'online').length ?? 0;
  const offlineCount = clients?.filter((c) => c.status === 'offline').length ?? 0;
  const unknownCount = (clients?.length ?? 0) - onlineCount - offlineCount;

  return (
    <div className="space-y-4 max-w-5xl">
      <PageHeader
        icon={Server}
        tone="slate"
        title={t('nav.distributed')}
        subtitle={t('distributed.subtitle')}
        actions={
          <>
            <label
              className={cx(
                'hidden sm:inline-flex select-none items-center gap-1.5 text-xs',
                hasToken ? 'cursor-pointer text-ink-600 dark:text-ink-300' : 'cursor-not-allowed text-ink-400 dark:text-ink-600',
              )}
              title={hasToken ? t('distributed.auto_refresh_hint') : t('distributed.auto_refresh_locked')}
            >
              <input
                type="checkbox"
                className="rounded border-ink-300 text-accent-600 focus:ring-accent-500 disabled:opacity-50"
                checked={autoRefresh}
                disabled={!hasToken}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              {t('distributed.auto_refresh')}
            </label>
            <Button size="sm" variant="secondary" onClick={() => void handleRefresh()} disabled={!hasToken || loading}>
              <RefreshCw size={13} className={cx(loading && 'animate-spin')} />
              {t('distributed.refresh')}
            </Button>
          </>
        }
      />

      {clients && clients.length > 0 && (
        <StatStrip
          stats={[
            { label: t('distributed.stat.total'), value: clients.length },
            { label: t('distributed.stat.online'), value: onlineCount, dotClass: 'bg-emerald-500' },
            { label: t('distributed.stat.offline'), value: offlineCount, dotClass: 'bg-rose-500' },
            ...(unknownCount > 0 ? [{ label: t('distributed.stat.unknown'), value: unknownCount, dotClass: 'bg-amber-400' }] : []),
          ]}
        />
      )}

      {/* 服务接入 / 断开 */}
      <Card>
        <CardHeader
          title={t('distributed.connect.title')}
          subtitle={t('distributed.connect.subtitle')}
        />
        {hasToken ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 text-sm text-ink-700 dark:text-ink-300">
              <span className="dot-ok" aria-hidden />
              {t('distributed.connected')}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setShowRaw(!showRaw)}>
                {showRaw ? t('distributed.hide_raw') : t('distributed.show_raw')}
              </Button>
              <Button size="sm" variant="ghost" className="text-rose-600 dark:text-rose-400" onClick={handleDisconnect}>
                <LogOut size={13} /> {t('distributed.disconnect')}
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleConnect} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="field-label" htmlFor="cs-user">{t('distributed.username_label')}</label>
                <input
                  id="cs-user"
                  type="text"
                  className="input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                />
              </div>
              <div>
                <label className="field-label" htmlFor="cs-pass">{t('distributed.password_label')}</label>
                <input
                  id="cs-pass"
                  type="password"
                  className="input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </div>
            </div>
            <Button variant="primary" type="submit" disabled={connecting}>
              <LogIn size={14} />
              {connecting ? t('distributed.connect.connecting') : t('distributed.connect.action')}
            </Button>
          </form>
        )}
      </Card>

      {showRaw && rawPayload !== null && (
        <Card>
          <CardHeader title={t('distributed.raw.title')} subtitle={t('distributed.raw.subtitle')} />
          <pre className="code-block max-h-[320px] overflow-auto">{JSON.stringify(rawPayload, null, 2)}</pre>
        </Card>
      )}

      {/* 拉取失败 */}
      {listError && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="inline-flex items-center gap-2 text-xs text-rose-600 dark:text-rose-400">
              <WifiOff size={14} className="shrink-0" />
              {t('distributed.error.fetch_failed').replace('{error}', listError)}
            </p>
            <Button size="sm" variant="secondary" onClick={() => void loadClients()}>
              {t('common.retry')}
            </Button>
          </div>
        </Card>
      )}

      {/* 加载骨架 */}
      {loading && clients === null && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label={t('distributed.loading')}>
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      )}

      {/* 空态引导 */}
      {!hasToken && !loading && (
        <Card>
          <EmptyState
            icon={<Server size={36} strokeWidth={1.5} />}
            title={t('distributed.empty.no_conn.title')}
            description={t('distributed.empty.no_conn.desc')}
          />
        </Card>
      )}
      {hasToken && !loading && !listError && clients !== null && clients.length === 0 && (
        <Card>
          <EmptyState
            icon={<Wifi size={36} strokeWidth={1.5} />}
            title={t('distributed.empty.no_nodes.title')}
            description={t('distributed.empty.no_nodes.desc')}
            action={
              <Button size="sm" variant="secondary" onClick={() => void loadClients()}>
                <RefreshCw size={13} /> {t('distributed.reload')}
              </Button>
            }
          />
        </Card>
      )}

      {/* 节点卡片列表 */}
      {clients && clients.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {clients.map((node) => {
            const online = node.status === 'online';
            return (
              <div key={node.id} className={cx('card card-hover p-4', node.status === 'offline' && 'opacity-70')}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden
                      className={cx(
                        'h-2 w-2 shrink-0 rounded-full',
                        online && 'bg-emerald-500',
                        node.status === 'offline' && 'bg-ink-300 dark:bg-ink-600',
                        node.status === 'unknown' && 'bg-amber-400',
                      )}
                    />
                    <span className="truncate text-sm font-medium text-ink-900 dark:text-ink-100" title={node.name}>
                      {node.name}
                    </span>
                  </div>
                  <Badge tone={online ? 'success' : node.status === 'offline' ? 'neutral' : 'warning'}>
                    {online ? t('distributed.node.online') : node.status === 'offline' ? t('distributed.node.offline') : node.rawStatus || t('distributed.node.unknown')}
                  </Badge>
                </div>

                <p className="mt-1.5 truncate font-mono text-xs text-ink-500 dark:text-ink-400" title={node.address ?? undefined}>
                  {node.address ?? t('distributed.node.address_unknown')}
                </p>

                {(node.roles.length > 0 || node.version) && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    {node.roles.map((role) => (
                      <Badge key={role} tone="accent">{role}</Badge>
                    ))}
                    {node.version && (
                      <span className="chip bg-ink-100 text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-400 dark:border-ink-700">
                        v{node.version}
                      </span>
                    )}
                  </div>
                )}

                <div className="mt-3 flex items-center gap-4 border-t border-ink-100 dark:border-ink-800/60 pt-2.5 text-2xs text-ink-400 dark:text-ink-500">
                  <span>
                    {t('distributed.node.latency')}
                    <span className="ml-1 font-mono tabular-nums text-ink-600 dark:text-ink-300">
                      {node.latencyMs != null ? `${node.latencyMs}ms` : '—'}
                    </span>
                  </span>
                  <span className="min-w-0 truncate">
                    {t('distributed.node.last_seen')}
                    <span className="ml-1 text-ink-600 dark:text-ink-300">{node.lastSeen ? formatRelativeTime(node.lastSeen) : '—'}</span>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
