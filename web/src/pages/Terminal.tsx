import { useEffect, useRef, useState } from 'react';
import { Terminal as TermIcon, Trash2, Pause, Play } from 'lucide-react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { PYTHON_API_BASE_URL } from '../services/api';
import { cx } from '../lib/utils';

type LogSource = 'cpp' | 'python';

interface LogEntry {
  timestamp?: string;
  level?: string;
  message: string;
}

const LEVEL_COLOR: Record<string, string> = {
  ERROR: 'text-rose-400',
  WARN: 'text-amber-400',
  WARNING: 'text-amber-400',
  INFO: 'text-ink-300',
  DEBUG: 'text-ink-500',
};

export default function Terminal() {
  const [source, setSource] = useState<LogSource>('cpp');
  const [logs, setLogs] = useState<Record<LogSource, LogEntry[]>>({ cpp: [], python: [] });
  const [streaming, setStreaming] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const esRef = useRef<EventSource | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

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
  }, [logs, autoScroll]);

  const entries = logs[source];

  return (
    <div className="space-y-4 max-w-6xl">
      <Card padded={false}>
        <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800 flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
            {(['cpp', 'python'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSource(s)}
                className={cx(
                  'px-3 py-1.5 text-xs font-medium transition-colors',
                  source === s
                    ? 'bg-accent-600 text-white'
                    : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
                )}
              >
                {s === 'cpp' ? 'C++ 后端' : 'Python 服务'}
              </button>
            ))}
          </div>

          <span className={cx('chip', streaming ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20' : 'bg-ink-100 text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-400 dark:border-ink-700')}>
            {streaming ? '已连接' : '未连接'}
          </span>

          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => setAutoScroll(!autoScroll)}>
              {autoScroll ? <Pause size={13} /> : <Play size={13} />}
              自动滚动
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setLogs((prev) => ({ ...prev, [source]: [] }))}>
              <Trash2 size={13} /> 清空
            </Button>
          </div>
        </div>

        <div className="bg-ink-950 rounded-b-lg h-[520px] overflow-y-auto p-4 font-mono text-xs leading-relaxed">
          {entries.length === 0 ? (
            <p className="text-ink-500 flex items-center gap-2">
              <TermIcon size={14} />
              等待日志输出…
            </p>
          ) : (
            entries.map((entry, i) => (
              <div key={i} className="flex gap-2 py-0.5">
                {entry.timestamp && (
                  <span className="text-ink-600 shrink-0">{entry.timestamp}</span>
                )}
                {entry.level && (
                  <span className={cx('shrink-0 w-14', LEVEL_COLOR[entry.level] ?? 'text-ink-300')}>
                    {entry.level}
                  </span>
                )}
                <span className="text-ink-200 break-all">{entry.message}</span>
              </div>
            ))
          )}
          <div ref={endRef} />
        </div>
      </Card>
    </div>
  );
}
