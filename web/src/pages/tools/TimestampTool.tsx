import { useMemo, useState } from 'react';
import { Clock, Trash2 } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { cn, formatRelativeTime } from '../../lib/utils';
import { ResultRow } from './shared';

/* ---------------------------------------------------------------------------
 * 时间戳转换：Epoch（秒 / 毫秒 / 微秒 / 纳秒）与日期字符串双向互转。
 * 输入自动识别位数；非数字输入按 Date.parse（ISO 优先，其余走浏览器解析）。
 * ------------------------------------------------------------------------- */

interface ParsedTime {
  ms: number;
  kind: string;
}

function parseTimeInput(raw: string): ParsedTime | null {
  const s = raw.trim();
  if (!s) return null;
  if (/^-?\d+$/.test(s)) {
    const digits = s.replace(/^-/, '');
    const n = Number(s);
    if (digits.length === 10) return { ms: n * 1000, kind: 'Epoch 秒（10 位）' };
    if (digits.length === 13) return { ms: n, kind: 'Epoch 毫秒（13 位）' };
    if (digits.length === 16) return { ms: n / 1000, kind: 'Epoch 微秒（16 位）' };
    if (digits.length === 19) return { ms: n / 1e6, kind: 'Epoch 纳秒（19 位）' };
    return null;
  }
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : { ms: t, kind: '日期字符串' };
}

const pad = (n: number): string => String(n).padStart(2, '0');

export default function TimestampTool() {
  const [input, setInput] = useState('');

  const parsed = useMemo(() => parseTimeInput(input), [input]);
  const date = useMemo(() => (parsed ? new Date(parsed.ms) : null), [parsed]);
  const valid = date !== null && !Number.isNaN(date.getTime());

  const rows = useMemo(() => {
    if (!valid || !date || !parsed) return [];
    const local = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    const utc = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
    return [
      { label: '本地时间', value: local },
      { label: 'UTC', value: `${utc} UTC` },
      { label: 'ISO 8601', value: date.toISOString() },
      { label: 'Unix 秒', value: String(Math.floor(parsed.ms / 1000)) },
      { label: 'Unix 毫秒', value: String(Math.round(parsed.ms)) },
      { label: '星期', value: `星期${'日一二三四五六'[date.getDay()]}` },
      { label: '相对时间', value: formatRelativeTime(parsed.ms) },
    ];
  }, [valid, date, parsed]);

  const statusChip = (() => {
    if (!input.trim()) {
      return (
        <span className="text-2xs text-ink-400 dark:text-ink-500">
          支持自动识别：10/13 位（另兼容 16/19 位微秒/纳秒）Epoch，或任意日期字符串
        </span>
      );
    }
    if (valid && parsed) {
      return (
        <span className="chip bg-accent-50 text-accent-700 dark:bg-accent-500/10 dark:text-accent-300">
          已识别：{parsed.kind}
        </span>
      );
    }
    return (
      <span className="chip bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
        无法识别的时间格式
      </span>
    );
  })();

  return (
    <Card>
      <CardHeader
        title="时间戳转换"
        subtitle="Epoch 与本地时间 / UTC / ISO 8601 双向转换，输入即算"
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => setInput(String(Date.now()))}>
              <Clock size={13} />
              当前时间
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setInput('')}>
              <Trash2 size={13} />
              清空
            </Button>
          </>
        }
      />

      <label className="field-label" htmlFor="ts-input">输入（Epoch 或日期字符串）</label>
      <input
        id="ts-input"
        type="text"
        className={cn('input font-mono', input && !valid && 'border-amber-400 dark:border-amber-500/60')}
        placeholder="例如 1756419200、1756419200000 或 2026-08-29 12:30:00"
        value={input}
        spellCheck={false}
        onChange={(e) => setInput(e.target.value)}
      />
      <div className="mt-2">{statusChip}</div>

      <div className="mt-4">
        {rows.length > 0 ? (
          rows.map((row) => <ResultRow key={row.label} label={row.label} value={row.value} />)
        ) : (
          <p className="text-xs text-ink-400 dark:text-ink-500">输入有效时间后在此显示全部格式</p>
        )}
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-ink-400 dark:text-ink-500">
        非数字输入按 Date.parse 解析：ISO 8601 按标准处理，无时区的本地格式（如 2026-08-29 12:30:00）按浏览器时区解析；
        识别为时间戳时以浏览器时区展示本地时间。
      </p>
    </Card>
  );
}
