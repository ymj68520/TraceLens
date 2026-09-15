import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Brain,
  Copy,
  Database,
  Download,
  HardDrive,
  Info,
  Keyboard,
  Network,
  Palette,
  RefreshCw,
  Server,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Trash2,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { updateSettings, resetSettings } from '../store/settingsSlice';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { PageHeader, Segmented, StatStrip } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import { useTranslation } from '../hooks/useTranslation';
import type { TranslationKey } from '../locales/keys';
import { cx, formatBytes, formatDateTime } from '../lib/utils';
import type { Language } from '../types/locale';
import pkg from '../../package.json';
import {
  CPP_BASE_URL,
  CS_API_BASE_URL,
  PYTHON_API_BASE_URL,
} from '../services/api';
import { getSystemHealth, getPythonHealth, getRedisStatus } from '../services/systemService';
import { getGraphitiStatus } from '../services/graphitiService';
import { getLLMStatus } from '../services/llmService';

/* ---------------------------------------------------------------------------
 * 设置中心：左侧锚点导航 + 多分区卡片。
 * 分区：外观 / 任务偏好 / 服务地址 / 服务状态 / 数据管理 / 关于。
 * ------------------------------------------------------------------------- */

type SectionId = 'appearance' | 'tasks' | 'api' | 'services' | 'data' | 'about';

const SECTIONS: Array<{ id: SectionId; labelKey: TranslationKey; icon: LucideIcon }> = [
  { id: 'appearance', labelKey: 'settings.section.appearance', icon: Palette },
  { id: 'tasks', labelKey: 'settings.section.tasks', icon: SlidersHorizontal },
  { id: 'api', labelKey: 'settings.section.api', icon: Network },
  { id: 'services', labelKey: 'settings.section.services', icon: Activity },
  { id: 'data', labelKey: 'settings.section.data', icon: Database },
  { id: 'about', labelKey: 'settings.section.about', icon: Info },
];

const sectionEl = (id: SectionId) => document.getElementById(`settings-${id}`);

/* ------------------------------ 服务状态探测 ------------------------------ */

type ProbeStatus = 'checking' | 'online' | 'offline';

interface ServiceRow {
  key: string;
  labelKey: TranslationKey;
  Icon: LucideIcon;
  status: ProbeStatus;
  latency: number | null;
}

const INITIAL_SERVICES: ServiceRow[] = [
  { key: 'cpp', labelKey: 'settings.service.cpp', Icon: Zap, status: 'checking', latency: null },
  { key: 'python', labelKey: 'settings.service.python', Icon: Server, status: 'checking', latency: null },
  { key: 'neo4j', labelKey: 'settings.service.neo4j', Icon: Database, status: 'checking', latency: null },
  { key: 'redis', labelKey: 'settings.service.redis', Icon: HardDrive, status: 'checking', latency: null },
  { key: 'llm', labelKey: 'settings.service.llm', Icon: Brain, status: 'checking', latency: null },
];

async function probe<T>(
  fn: () => Promise<T>,
  ok: (result: T) => boolean = () => true,
): Promise<{ status: ProbeStatus; latency: number | null }> {
  const start = Date.now();
  try {
    const result = await fn();
    return { status: ok(result) ? 'online' : 'offline', latency: Date.now() - start };
  } catch {
    return { status: 'offline', latency: null };
  }
}

/* ------------------------------ 本地存储统计 ------------------------------ */

/** 登录凭据相关键：清理缓存时始终保留。 */
const AUTH_KEYS = new Set(['auth_token', 'cs_auth_token', 'auth_user']);
const SETTINGS_KEY = 'forensics_settings';
/** UTF-16 编码，每个字符占 2 字节 — 本地估算口径。 */
const bytesOf = (key: string, value: string) => (key.length + value.length) * 2;

interface KeyStat {
  key: string;
  bytes: number;
  kind: 'credential' | 'settings' | 'cache';
}

/** 存储键分类 -> 徽标翻译键 */
const KIND_LABEL: Record<KeyStat['kind'], TranslationKey> = {
  credential: 'settings.data.kind.credential',
  settings: 'settings.data.kind.settings',
  cache: 'settings.data.kind.cache',
};

const scanLocalStorage = (): KeyStat[] => {
  const stats: KeyStat[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key === null) continue;
    const value = localStorage.getItem(key) ?? '';
    const kind: KeyStat['kind'] = AUTH_KEYS.has(key) ? 'credential' : key === SETTINGS_KEY ? 'settings' : 'cache';
    stats.push({ key, bytes: bytesOf(key, value), kind });
  }
  return stats.sort((a, b) => b.bytes - a.bytes);
};

/* --------------------------------- 页面 --------------------------------- */

const STATUS_BADGE: Record<ProbeStatus, { tone: 'success' | 'warning' | 'danger'; textKey: TranslationKey }> = {
  online: { tone: 'success', textKey: 'system.online' },
  checking: { tone: 'warning', textKey: 'system.checking' },
  offline: { tone: 'danger', textKey: 'system.offline' },
};

const BACKENDS: Array<{ labelKey: TranslationKey; url: string }> = [
  { labelKey: 'settings.service.cpp', url: CPP_BASE_URL },
  { labelKey: 'settings.service.python', url: PYTHON_API_BASE_URL },
  { labelKey: 'settings.service.cs', url: CS_API_BASE_URL },
];

export default function Settings() {
  const dispatch = useAppDispatch();
  const settings = useAppSelector((state) => state.settings);
  const toast = useToast();
  const { t } = useTranslation();
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [activeSection, setActiveSection] = useState<SectionId>('appearance');

  /* 服务状态探测 */
  const [services, setServices] = useState<ServiceRow[]>(INITIAL_SERVICES);
  const [probing, setProbing] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<number | null>(null);

  /* 本地存储统计 */
  const [keyStats, setKeyStats] = useState<KeyStat[]>([]);

  const set = (patch: Partial<typeof settings>) => dispatch(updateSettings(patch));

  const scrollToSection = useCallback((id: SectionId) => {
    setActiveSection(id);
    sectionEl(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  /* 滚动监听：高亮当前分区（轻量 scroll-spy） */
  useEffect(() => {
    const onScroll = () => {
      let current: SectionId = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = sectionEl(s.id);
        if (el && el.getBoundingClientRect().top <= 120) current = s.id;
      }
      setActiveSection(current);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const patchService = useCallback((key: string, r: { status: ProbeStatus; latency: number | null }) => {
    setServices((prev) => prev.map((s) => (s.key === key ? { ...s, ...r } : s)));
  }, []);

  const runProbes = useCallback(() => {
    setProbing(true);
    setServices((prev) => prev.map((s) => ({ ...s, status: 'checking' as const, latency: null })));
    const jobs: Array<[string, Promise<{ status: ProbeStatus; latency: number | null }>]> = [
      ['cpp', probe(getSystemHealth)],
      ['python', probe(getPythonHealth)],
      ['neo4j', probe(getGraphitiStatus, (s) => Boolean((s as { neo4j_connected?: boolean })?.neo4j_connected))],
      ['redis', probe(getRedisStatus, (s) => Boolean((s as { connected?: boolean })?.connected))],
      [
        'llm',
        probe(getLLMStatus, (s) => {
          const st = (s as { status?: string })?.status;
          return st === 'available' || st === 'healthy';
        }),
      ],
    ];
    jobs.forEach(([key, p]) => {
      void p.then((r) => patchService(key, r));
    });
    void Promise.allSettled(jobs.map(([, p]) => p)).then(() => {
      setProbing(false);
      setLastCheckedAt(Date.now());
    });
  }, [patchService]);

  const rescanStorage = useCallback(() => setKeyStats(scanLocalStorage()), []);

  useEffect(() => {
    runProbes();
    rescanStorage();
  }, [runProbes, rescanStorage]);

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t('settings.toast.address_copied').replace('{label}', label));
    } catch {
      toast.error(t('settings.toast.copy_failed'));
    }
  };

  const exportSettings = () => {
    const payload = {
      app: 'TraceLens Web',
      version: pkg.version,
      exported_at: new Date().toISOString(),
      settings,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tracelens-settings-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(t('settings.toast.exported'));
  };

  const totalBytes = keyStats.reduce((sum, s) => sum + s.bytes, 0);
  const cacheStats = keyStats.filter((s) => s.kind !== 'credential');
  const cacheBytes = cacheStats.reduce((sum, s) => sum + s.bytes, 0);

  const handleClearCache = () => {
    let cleared = 0;
    for (let i = localStorage.length - 1; i >= 0; i -= 1) {
      const key = localStorage.key(i);
      if (key === null || AUTH_KEYS.has(key)) continue;
      localStorage.removeItem(key);
      cleared += 1;
    }
    rescanStorage();
    toast.success(t('settings.toast.cache_cleared').replace('{n}', String(cleared)));
  };

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={SettingsIcon}
        tone="slate"
        title={t('settings.title')}
        subtitle={t('settings.subtitle')}
      />

      {/* 移动端：横向分段导航 */}
      <div className="lg:hidden overflow-x-auto -mx-1 px-1 pb-1 mb-4">
        <Segmented
          options={SECTIONS.map((s) => ({ value: s.id, label: t(s.labelKey), icon: s.icon }))}
          value={activeSection}
          onChange={scrollToSection}
        />
      </div>

      <div className="lg:grid lg:grid-cols-[10.5rem_minmax(0,1fr)] lg:gap-8">
        {/* 桌面端：sticky 锚点导航 */}
        <nav className="hidden lg:block" aria-label={t('settings.nav_aria')}>
          <ul className="sticky top-20 space-y-0.5">
            {SECTIONS.map((s) => {
              const Icon = s.icon;
              const active = s.id === activeSection;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => scrollToSection(s.id)}
                    aria-current={active ? 'true' : undefined}
                    className={cx(
                      'w-full flex items-center gap-2.5 rounded-md px-3 py-[7px] text-[13px] font-medium transition-colors text-left',
                      active
                        ? 'bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300'
                        : 'text-ink-600 dark:text-ink-400 hover:text-ink-900 dark:hover:text-ink-100 hover:bg-ink-100/80 dark:hover:bg-white/5',
                    )}
                  >
                    <Icon
                      size={15}
                      strokeWidth={active ? 2 : 1.75}
                      className={cx('shrink-0', active ? 'text-accent-600 dark:text-accent-400' : 'text-ink-400 dark:text-ink-500')}
                    />
                    {t(s.labelKey)}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="space-y-4 min-w-0">
          {/* 外观 */}
          <Card id="settings-appearance" className="scroll-mt-24">
            <CardHeader title={t('settings.section.appearance')} subtitle={t('settings.appearance.subtitle')} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="field-label" htmlFor="set-theme">{t('settings.theme')}</label>
                <select
                  id="set-theme"
                  className="select"
                  value={settings.theme}
                  onChange={(e) => {
                    const theme = e.target.value as 'light' | 'dark';
                    set({ theme });
                    toast.info(t(theme === 'dark' ? 'settings.toast.theme_dark' : 'settings.toast.theme_light'));
                  }}
                >
                  <option value="light">{t('settings.theme.light')}</option>
                  <option value="dark">{t('settings.theme.dark')}</option>
                </select>
              </div>
              <div>
                <label className="field-label" htmlFor="set-lang">{t('settings.language')}</label>
                <select
                  id="set-lang"
                  className="select"
                  value={settings.language}
                  onChange={(e) => {
                    set({ language: e.target.value as Language });
                    toast.success(t('settings.toast.language_switched'));
                  }}
                >
                  <option value="zh">{t('settings.language.zh')}</option>
                  <option value="en">{t('settings.language.en')}</option>
                </select>
              </div>
            </div>
          </Card>

          {/* 任务偏好 */}
          <Card id="settings-tasks" className="scroll-mt-24">
            <CardHeader title={t('settings.section.tasks')} subtitle={t('settings.tasks.subtitle')} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="field-label" htmlFor="set-ipp">{t('settings.items_per_page')}</label>
                <input
                  id="set-ipp"
                  type="number"
                  min={5}
                  max={200}
                  className="input"
                  value={settings.itemsPerPage}
                  onChange={(e) => set({ itemsPerPage: Number(e.target.value) || 20 })}
                />
              </div>
              <div>
                <label className="field-label" htmlFor="set-interval">{t('settings.refresh_interval')}</label>
                <input
                  id="set-interval"
                  type="number"
                  min={1000}
                  step={500}
                  className="input"
                  value={settings.refreshInterval}
                  onChange={(e) => set({ refreshInterval: Number(e.target.value) || 5000 })}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-ink-700 dark:text-ink-300 sm:col-span-2">
                <input
                  type="checkbox"
                  className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  checked={settings.autoRefresh}
                  onChange={(e) => {
                    set({ autoRefresh: e.target.checked });
                    toast.success(t(e.target.checked ? 'settings.toast.auto_refresh_on' : 'settings.toast.auto_refresh_off'));
                  }}
                />
                {t('settings.auto_refresh')}
              </label>
              <label className="flex items-center gap-2 text-sm text-ink-700 dark:text-ink-300 sm:col-span-2">
                <input
                  type="checkbox"
                  className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  checked={settings.showTerminal}
                  onChange={(e) => {
                    set({ showTerminal: e.target.checked });
                    toast.success(t(e.target.checked ? 'settings.toast.terminal_shown' : 'settings.toast.terminal_hidden'));
                  }}
                />
                {t('settings.show_terminal')}
              </label>
            </div>
          </Card>

          {/* 服务地址 */}
          <Card id="settings-api" className="scroll-mt-24">
            <CardHeader title={t('settings.section.api')} subtitle={t('settings.api.subtitle')} />
            <div className="grid grid-cols-1 gap-4">
              <div>
                <label className="field-label" htmlFor="set-api">{t('settings.api.cpp_url')}</label>
                <input
                  id="set-api"
                  type="text"
                  className="input font-mono text-xs"
                  value={settings.apiUrl}
                  onChange={(e) => set({ apiUrl: e.target.value })}
                />
              </div>
              <div>
                <label className="field-label" htmlFor="set-pyapi">{t('settings.api.python_url')}</label>
                <input
                  id="set-pyapi"
                  type="text"
                  className="input font-mono text-xs"
                  value={settings.pythonApiUrl}
                  onChange={(e) => set({ pythonApiUrl: e.target.value })}
                />
              </div>
            </div>
          </Card>

          {/* 服务状态 */}
          <Card id="settings-services" className="scroll-mt-24">
            <CardHeader
              title={t('settings.section.services')}
              subtitle={t('settings.services.subtitle')}
              actions={
                <Button size="sm" variant="ghost" onClick={runProbes} disabled={probing}>
                  <RefreshCw size={13} className={cx(probing && 'animate-spin')} />
                  {t('settings.services.recheck')}
                </Button>
              }
            />
            <ul className="divide-y divide-ink-100 dark:divide-ink-800/60">
              {services.map((svc) => {
                const badge = STATUS_BADGE[svc.status];
                return (
                  <li key={svc.key} className="flex items-center gap-3 py-2.5">
                    <svc.Icon size={15} className="shrink-0 text-ink-400 dark:text-ink-500" />
                    <span className="flex-1 min-w-0 truncate text-xs font-medium text-ink-800 dark:text-ink-200">
                      {t(svc.labelKey)}
                    </span>
                    {svc.latency != null && (
                      <span className="shrink-0 font-mono text-2xs tabular-nums text-ink-400 dark:text-ink-500">
                        {svc.latency}ms
                      </span>
                    )}
                    <Badge tone={badge.tone} dot className="min-w-[56px] justify-center">
                      {t(badge.textKey)}
                    </Badge>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-2xs text-ink-400 dark:text-ink-500">
              {t('settings.services.last_checked').replace('{time}', lastCheckedAt ? formatDateTime(lastCheckedAt) : t('settings.services.not_yet'))}
            </p>
          </Card>

          {/* 数据管理 */}
          <Card id="settings-data" className="scroll-mt-24">
            <CardHeader title={t('settings.section.data')} subtitle={t('settings.data.subtitle')} />
            <StatStrip
              stats={[
                { label: t('settings.data.total_usage'), value: formatBytes(totalBytes) },
                { label: t('settings.data.key_count'), value: keyStats.length },
                {
                  label: t('settings.data.clearable'),
                  value: t('settings.data.clearable_value').replace('{n}', String(cacheStats.length)).replace('{bytes}', formatBytes(cacheBytes)),
                  dotClass: 'bg-amber-400',
                },
                { label: t('settings.data.credential_keys'), value: keyStats.length - cacheStats.length, dotClass: 'bg-emerald-500' },
              ]}
            />
            <ul className="mt-3 divide-y divide-ink-100 dark:divide-ink-800/60 rounded-lg border border-ink-100 dark:border-ink-800/60">
              {keyStats.slice(0, 8).map((s) => (
                <li key={s.key} className="flex items-center gap-3 px-3 py-2">
                  <span className="flex-1 min-w-0 truncate font-mono text-2xs text-ink-700 dark:text-ink-300" title={s.key}>
                    {s.key}
                  </span>
                  <Badge tone={s.kind === 'credential' ? 'success' : s.kind === 'settings' ? 'accent' : 'neutral'}>{t(KIND_LABEL[s.kind])}</Badge>
                  <span className="w-16 shrink-0 text-right font-mono text-2xs tabular-nums text-ink-400 dark:text-ink-500">
                    {formatBytes(s.bytes)}
                  </span>
                </li>
              ))}
              {keyStats.length === 0 && (
                <li className="px-3 py-4 text-center text-2xs text-ink-400 dark:text-ink-500">{t('settings.data.empty')}</li>
              )}
            </ul>
            {keyStats.length > 8 && (
              <p className="mt-1.5 text-2xs text-ink-400 dark:text-ink-500">{t('settings.data.top_keys').replace('{n}', String(keyStats.length))}</p>
            )}
            {keyStats.length > 0 && (
              <p className="mt-1.5 text-2xs text-ink-400 dark:text-ink-500">{t('settings.data.bytes_note')}</p>
            )}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={exportSettings}>
                <Download size={13} />
                {t('settings.data.export')}
              </Button>
              <Button variant="danger" size="sm" onClick={() => setConfirmClear(true)}>
                <Trash2 size={13} />
                {t('settings.data.clear_cache')}
              </Button>
            </div>
          </Card>

          {/* 关于 */}
          <Card id="settings-about" className="scroll-mt-24">
            <CardHeader title={t('settings.section.about')} subtitle={t('settings.about.subtitle')} />
            <dl className="space-y-2.5 text-xs">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">{t('settings.about.web_version')}</dt>
                <dd className="font-mono text-ink-800 dark:text-ink-200">v{pkg.version}</dd>
              </div>
              {BACKENDS.map((b) => (
                <div key={b.labelKey} className="flex items-center justify-between gap-3">
                  <dt className="shrink-0 text-ink-500 dark:text-ink-400">{t(b.labelKey)}</dt>
                  <dd className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate font-mono text-ink-800 dark:text-ink-200">{b.url}</span>
                    <button
                      type="button"
                      onClick={() => void copyText(b.url, t(b.labelKey))}
                      className="shrink-0 rounded p-1 text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-600 dark:hover:bg-ink-800 dark:hover:text-ink-200"
                      aria-label={t('settings.about.copy_address').replace('{label}', t(b.labelKey))}
                    >
                      <Copy size={12} />
                    </button>
                  </dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-ink-100 dark:border-ink-800/60 bg-ink-50/60 dark:bg-ink-900/50 px-3 py-2.5">
              <Keyboard size={14} className="mt-0.5 shrink-0 text-ink-400 dark:text-ink-500" />
              <p className="text-2xs leading-relaxed text-ink-500 dark:text-ink-400">
                {t('settings.about.hint.prefix')} <span className="kbd">⌘K</span> / <span className="kbd">Ctrl</span> +{' '}
                <span className="kbd">K</span> {t('settings.about.hint.suffix')}
              </p>
            </div>
            <div className="mt-4 flex justify-end border-t border-ink-100 dark:border-ink-800/60 pt-3">
              <Button variant="ghost" className="text-rose-600 dark:text-rose-400" onClick={() => setConfirmReset(true)}>
                {t('settings.reset')}
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {/* 清理本地缓存确认 */}
      <ConfirmDialog
        open={confirmClear}
        title={t('settings.data.clear_cache')}
        danger
        message={t('settings.clear_cache_confirm')
          .replace('{n}', String(cacheStats.length))
          .replace('{bytes}', formatBytes(cacheBytes))}
        confirmText={t('settings.clear_action')}
        onConfirm={handleClearCache}
        onCancel={() => setConfirmClear(false)}
      />

      {/* 恢复默认设置确认 */}
      <ConfirmDialog
        open={confirmReset}
        title={t('settings.reset')}
        message={t('settings.reset_message')}
        confirmText={t('settings.reset_action')}
        onConfirm={() => {
          dispatch(resetSettings());
          setConfirmReset(false);
          toast.success(t('settings.toast.reset_done'));
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}
