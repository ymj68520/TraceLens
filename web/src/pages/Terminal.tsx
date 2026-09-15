import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  ChevronRight,
  Copy,
  Filter,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RotateCw,
  Terminal as TermIcon,
  Trash2,
  X,
} from 'lucide-react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import { useToast } from '../components/ui/Toast';
import { PYTHON_API_BASE_URL } from '../services/api';
import { cx } from '../lib/utils';
import { Terminal as TerminalIcon } from 'lucide-react';
import { PageHeader } from '../components/ui/PageScaffold';
import { useTranslation } from '../hooks/useTranslation';

type LogSource = 'cpp' | 'python';

interface LogEntry {
  timestamp?: string;
  level?: string;
  message: string;
}

interface SysLine {
  id: number;
  kind: 'cmd' | 'resp' | 'err';
  text: string;
}

const LEVEL_COLOR: Record<string, string> = {
  ERROR: 'text-rose-400',
  WARN: 'text-amber-400',
  WARNING: 'text-amber-400',
  INFO: 'text-ink-300',
  DEBUG: 'text-ink-500',
};

const HISTORY_KEY = 'tracelens_terminal_history';
const HISTORY_LIMIT = 50;

const loadHistory = (): string[] => {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string').slice(-HISTORY_LIMIT) : [];
  } catch {
    return [];
  }
};

const saveHistory = (items: string[]) => {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(-HISTORY_LIMIT)));
  } catch {
    /* 持久化失败时历史仅在当前会话内可用 */
  }
};

export default function Terminal() {
  const toast = useToast();
  const { t } = useTranslation();
  const [source, setSource] = useState<LogSource>('cpp');
  const [logs, setLogs] = useState<Record<LogSource, LogEntry[]>>({ cpp: [], python: [] });
  const [streaming, setStreaming] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const esRef = useRef<EventSource | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  /* 交互增强：命令历史 / 过滤 / 全屏 */
  const [history, setHistory] = useState<string[]>(loadHistory);
  const [histIndex, setHistIndex] = useState<number | null>(null);
  const [cmd, setCmd] = useState('');
  const [sysLines, setSysLines] = useState<SysLine[]>([]);
  const [filter, setFilter] = useState('');
  const [tailCount, setTailCount] = useState<number | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const sysIdRef = useRef(0);
  const cmdInputRef = useRef<HTMLInputElement>(null);

  const stop = () => {
    esRef.current?.close();
    esRef.current = null;
    setStreaming(false);
  };

  const start = (src: LogSource) => {
    stop();
    const url = `${PYTHON_API_BASE_URL}/api/system/logs-stream/${src}`;
    const es = new EventSource(url);
    esRef.current = es;
    setStreaming(true);

    es.onmessage = (event) => {
      let entry: LogEntry;
      try {
        entry = JSON.parse(event.data) as LogEntry;
      } catch {
        entry = { message: event.data as string, level: 'INFO' };
      }
      setLogs((prev) => ({
        ...prev,
        [src]: [...prev[src].slice(-499), entry],
      }));
    };
    es.onerror = () => stop();
  };

  useEffect(() => {
    start(source);
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, sysLines, autoScroll]);

  /* 全屏时支持 Esc 退出 */
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  /* 进入全屏后聚焦命令输入行 */
  useEffect(() => {
    if (fullscreen) cmdInputRef.current?.focus();
  }, [fullscreen]);

  const pushSys = (kind: SysLine['kind'], text: string) => {
    sysIdRef.current += 1;
    const line: SysLine = { id: sysIdRef.current, kind, text };
    setSysLines((prev) => [...prev, line].slice(-HISTORY_LIMIT));
  };

  const switchSource = (src: LogSource) => {
    if (src === source) return;
    setSource(src);
    setSysLines([]);
    setHistIndex(null);
  };

  const rememberHistory = (entry: string) => {
    setHistory((prev) => {
      const next = [...prev.filter((h) => h !== entry), entry].slice(-HISTORY_LIMIT);
      saveHistory(next);
      return next;
    });
    setHistIndex(null);
  };

  /* 本地控制台命令：不依赖任何后端执行接口，全部在浏览器内完成 */
  const runCommand = (raw: string) => {
    const input = raw.trim();
    const [name, ...rest] = input.split(/\s+/);
    const arg = rest.join(' ');

    if (name === 'clear') {
      setLogs((prev) => ({ ...prev, [source]: [] }));
      setSysLines([]);
      setFilter('');
      setTailCount(null);
      return;
    }
    if (!input) return;
    pushSys('cmd', input);
    rememberHistory(input);

    switch (name) {
      case 'help':
        pushSys('resp', t('terminal.cmd.help'));
        break;
      case 'filter':
        if (arg) {
          setFilter(arg);
          pushSys('resp', t('terminal.cmd.filter_applied').replace('{kw}', arg));
        } else {
          setFilter('');
          pushSys('resp', t('terminal.cmd.filter_cleared'));
        }
        break;
      case 'tail': {
        const n = Number(arg);
        if (Number.isInteger(n) && n > 0) {
          setTailCount(n);
          pushSys('resp', t('terminal.cmd.tail_applied').replace('{n}', String(n)));
        } else {
          pushSys('err', t('terminal.cmd.tail_usage'));
        }
        break;
      }
      case 'source':
        if (arg === 'cpp' || arg === 'python') {
          switchSource(arg);
          pushSys('cmd', input);
          pushSys('resp', t('terminal.cmd.source_applied').replace('{source}', arg === 'cpp' ? t('terminal.source.cpp') : t('terminal.source.python')));
        } else {
          pushSys('err', t('terminal.cmd.source_usage'));
        }
        break;
      case 'autoscroll':
        if (arg === 'on' || arg === 'off') {
          setAutoScroll(arg === 'on');
          pushSys('resp', arg === 'on' ? t('terminal.cmd.autoscroll_on') : t('terminal.cmd.autoscroll_off'));
        } else {
          pushSys('err', t('terminal.cmd.autoscroll_usage'));
        }
        break;
      case 'history':
        if (history.length === 0) pushSys('resp', t('terminal.cmd.history_empty'));
        else history.slice(-10).forEach((h, i) => pushSys('resp', `${i + 1}. ${h}`));
        break;
      default:
        pushSys('err', t('terminal.cmd.unknown').replace('{name}', name));
    }
  };

  const handleCmdKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      runCommand(cmd);
      setCmd('');
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length === 0) return;
      const next = histIndex === null ? history.length - 1 : Math.max(0, histIndex - 1);
      setHistIndex(next);
      setCmd(history[next]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIndex === null) return;
      const next = histIndex + 1;
      if (next >= history.length) {
        setHistIndex(null);
        setCmd('');
      } else {
        setHistIndex(next);
        setCmd(history[next]);
      }
    }
  };

  const entries = logs[source];

  const visibleEntries = useMemo(() => {
    let list = entries;
    if (filter) {
      const kw = filter.toLowerCase();
      list = list.filter(
        (e) => e.message.toLowerCase().includes(kw) || (e.level ?? '').toLowerCase() === kw,
      );
    }
    if (tailCount != null) list = list.slice(-tailCount);
    return list;
  }, [entries, filter, tailCount]);

  const handleCopy = async () => {
    const text = visibleEntries
      .map((e) => [e.timestamp, e.level, e.message].filter(Boolean).join('  '))
      .join('\n');
    if (!text) {
      toast.info(t('terminal.copy.none'));
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t('terminal.copy.success').replace('{n}', String(visibleEntries.length)));
    } catch {
      toast.error(t('terminal.copy.failed'));
    }
  };

  /* 工具栏与终端主体在全屏 / 常规两种容器间复用 */
  const toolbar = (
    <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-4 py-2.5 dark:border-ink-800">
      <div className="flex overflow-hidden rounded-md border border-ink-200 dark:border-ink-700">
        {(['cpp', 'python'] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => switchSource(s)}
            className={cx(
              'px-3 py-1.5 text-xs font-medium transition-colors',
              source === s
                ? 'bg-accent-600 text-white'
                : 'bg-white text-ink-600 hover:bg-ink-50 dark:bg-ink-900 dark:text-ink-300 dark:hover:bg-ink-800',
            )}
          >
            {s === 'cpp' ? t('terminal.source.cpp') : t('terminal.source.python')}
          </button>
        ))}
      </div>

      <span
        title={streaming ? t('terminal.status.connected') : t('terminal.status.disconnected')}
        className="inline-flex"
      >
        <Badge dot tone={streaming ? 'success' : 'neutral'}>
          {streaming ? t('terminal.badge.connected') : t('terminal.badge.disconnected')}
        </Badge>
      </span>
      {!streaming && (
        <Button size="sm" variant="ghost" onClick={() => start(source)}>
          <RotateCw size={12} /> {t('terminal.reconnect')}
        </Button>
      )}

      {filter && (
        <button
          type="button"
          onClick={() => setFilter('')}
          className="chip border border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300"
          title={t('terminal.clear_filter')}
        >
          <Filter size={11} />
          {filter}
          <X size={11} />
        </button>
      )}

      <span className="ml-auto hidden font-mono text-2xs tabular-nums text-ink-400 dark:text-ink-500 sm:inline">
        {t('terminal.entry_count').replace('{visible}', String(visibleEntries.length)).replace('{total}', String(entries.length))}
      </span>

      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => void handleCopy()} title={t('terminal.copy_tooltip')}>
          <Copy size={13} /> {t('terminal.copy')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setAutoScroll(!autoScroll)}>
          {autoScroll ? <Pause size={13} /> : <Play size={13} />}
          {t('terminal.auto_scroll')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setLogs((prev) => ({ ...prev, [source]: [] }));
            setSysLines([]);
            setFilter('');
            setTailCount(null);
          }}
        >
          <Trash2 size={13} /> {t('terminal.clear_screen')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setFullscreen(!fullscreen)} title={t('terminal.fullscreen_tooltip')}>
          {fullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          {fullscreen ? t('terminal.exit_fullscreen') : t('terminal.fullscreen')}
        </Button>
      </div>
    </div>
  );

  const panel = (
    <Card padded={false} className={cx('flex flex-col overflow-hidden', fullscreen && 'h-full shadow-pop')}>
      {toolbar}
      <div
        className={cx(
          'min-h-0 flex-1 overflow-y-auto bg-ink-950 p-4 font-mono text-xs leading-relaxed',
          !fullscreen && 'h-[520px] flex-none',
        )}
      >
        {visibleEntries.length === 0 && sysLines.length === 0 ? (
          <p className="flex items-center gap-2 text-ink-500">
            <TermIcon size={14} />
            {filter ? t('terminal.empty.filtered') : t('terminal.empty.waiting')}
          </p>
        ) : (
          visibleEntries.map((entry, i) => (
            <div key={i} className="flex gap-2 py-0.5">
              {entry.timestamp && <span className="shrink-0 text-ink-600">{entry.timestamp}</span>}
              {entry.level && (
                <span className={cx('w-14 shrink-0', LEVEL_COLOR[entry.level] ?? 'text-ink-300')}>{entry.level}</span>
              )}
              <span className="break-all text-ink-200">{entry.message}</span>
            </div>
          ))
        )}
        {sysLines.map((line) => (
          <div key={line.id} className="flex gap-2 py-0.5">
            <span
              className={cx(
                'shrink-0',
                line.kind === 'cmd' && 'text-accent-400',
                line.kind === 'resp' && 'text-sky-300',
                line.kind === 'err' && 'text-rose-400',
              )}
            >
              {line.kind === 'cmd' ? '$' : '»'}
            </span>
            <span className={cx('break-all', line.kind === 'err' ? 'text-rose-300' : 'text-ink-300')}>{line.text}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {/* 本地控制台命令行：历史 ↑/↓ 回溯，最近 50 条持久化 */}
      <div className="flex shrink-0 items-center gap-2 border-t border-ink-800 bg-ink-950 px-4 py-2.5">
        <ChevronRight size={14} className="shrink-0 text-accent-400" />
        <input
          ref={cmdInputRef}
          type="text"
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={handleCmdKeyDown}
          placeholder={t('terminal.cmd.placeholder')}
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent font-mono text-xs text-ink-100 placeholder:text-ink-600 focus:outline-none"
          aria-label={t('terminal.cmd.aria')}
        />
        <kbd className="hidden text-2xs text-ink-600 sm:inline">{t('terminal.cmd.enter_hint')}</kbd>
      </div>
    </Card>
  );

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 flex animate-fade-in flex-col bg-ink-50 p-4 dark:bg-ink-950 lg:p-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <TerminalIcon size={18} className="shrink-0 text-accent-600 dark:text-accent-400" />
            <h1 className="truncate text-sm font-semibold text-ink-900 dark:text-white">{t('terminal.title')}</h1>
            <span
              title={streaming ? t('terminal.status.connected') : t('terminal.status.disconnected')}
              className="inline-flex"
            >
              <Badge dot tone={streaming ? 'success' : 'neutral'}>
                {streaming ? t('terminal.badge.connected') : t('terminal.badge.disconnected')}
              </Badge>
            </span>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setFullscreen(false)}>
            <Minimize2 size={13} /> {t('terminal.exit_fullscreen')} <span className="kbd">Esc</span>
          </Button>
        </div>
        {panel}
      </div>
    );
  }

  return (
    <div className="max-w-6xl space-y-4">
      <PageHeader icon={TerminalIcon} tone="slate" title={t('nav.terminal')} subtitle={t('terminal.subtitle')} />
      {panel}
    </div>
  );
}
