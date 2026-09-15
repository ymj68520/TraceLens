import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { StatStrip } from '../../components/ui/PageScaffold';
import { useDebouncedValue } from './shared';

/* ---------------------------------------------------------------------------
 * 字频 / 字符统计：字符数（码点）、UTF-8 字节、行数、词数、字符分布
 * 与 Top 20 字符频率条形图（纯 div 宽度条）。全部本地计算。
 * ------------------------------------------------------------------------- */

const CJK_RE = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/;

interface TextStats {
  chars: number;
  bytes: number;
  lines: number;
  words: number;
  latinWords: number;
  cjkChars: number;
  dist: Array<{ label: string; count: number }>;
  top: Array<{ ch: string; count: number }>;
}

function computeStats(text: string): TextStats {
  const cps = Array.from(text); // 按 Unicode 码点切分，emoji / 代理对计 1 字符
  const chars = cps.length;
  const bytes = new TextEncoder().encode(text).length;
  const lines = text.length === 0 ? 0 : text.split('\n').length;

  let cjkChars = 0;
  let latin = 0;
  let digit = 0;
  let space = 0;
  const freq = new Map<string, number>();
  for (const c of cps) {
    if (/\s/.test(c)) {
      space += 1;
      continue;
    }
    if (CJK_RE.test(c)) cjkChars += 1;
    else if (/[A-Za-z]/.test(c)) latin += 1;
    else if (/[0-9]/.test(c)) digit += 1;
    const cp = c.codePointAt(0) ?? 0;
    if (cp < 0x20 || cp === 0x7f) continue; // 控制字符不进频率榜
    freq.set(c, (freq.get(c) ?? 0) + 1);
  }

  const latinWords = text.match(/[A-Za-z0-9][A-Za-z0-9'_-]*/g)?.length ?? 0;
  const top = [...freq.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0].codePointAt(0) ?? 0) - (b[0].codePointAt(0) ?? 0))
    .slice(0, 20)
    .map(([ch, count]) => ({ ch, count }));

  return {
    chars,
    bytes,
    lines,
    words: latinWords + cjkChars,
    latinWords,
    cjkChars,
    dist: [
      { label: '中日韩', count: cjkChars },
      { label: '英文字母', count: latin },
      { label: '数字', count: digit },
      { label: '空白', count: space },
      { label: '其他', count: chars - cjkChars - latin - digit - space },
    ],
    top,
  };
}

/** 频率条 + 计数的行，dist 与 Top 20 共用。 */
function BarRow({ left, count, total, showPct, right }: { left: string; count: number; total: number; showPct?: boolean; right?: string }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 truncate text-xs text-ink-500 dark:text-ink-400">{left}</span>
      <div className="h-3 flex-1 overflow-hidden rounded bg-ink-100 dark:bg-ink-900">
        <div className="h-full rounded bg-accent-500/80 dark:bg-accent-500/60" style={{ width: `${Math.max(pct, count > 0 ? 1.5 : 0)}%` }} />
      </div>
      <span className="w-24 shrink-0 text-right font-mono text-2xs tabular-nums text-ink-500 dark:text-ink-400">
        {count}（{showPct ? `${pct.toFixed(1)}%` : (right ?? '')}）
      </span>
    </div>
  );
}

export default function TextStatsTool() {
  const [text, setText] = useState('');
  const debouncedText = useDebouncedValue(text, 200);
  const stats = useMemo(() => computeStats(debouncedText), [debouncedText]);

  const topMax = stats.top[0]?.count ?? 0;
  const distTotal = stats.dist.reduce((sum, d) => sum + d.count, 0);

  return (
    <Card>
      <CardHeader
        title="字频 / 字符统计"
        subtitle="字符、字节、行数、词数与字符频率分布，输入即算"
        actions={
          <Button variant="ghost" size="sm" onClick={() => setText('')}>
            <Trash2 size={13} />
            清空
          </Button>
        }
      />

      <label className="field-label" htmlFor="textstats-input">文本输入</label>
      <textarea
        id="textstats-input"
        className="input font-mono text-xs leading-relaxed"
        rows={5}
        spellCheck={false}
        placeholder="粘贴任意文本，自动统计"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="mt-4 space-y-5">
        <StatStrip
          stats={[
            { label: '字符（码点）', value: stats.chars },
            { label: 'UTF-8 字节', value: stats.bytes },
            { label: '行数', value: stats.lines },
            { label: '词数', value: stats.words },
          ]}
        />

        {debouncedText ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <p className="section-label mb-2.5">字符分布</p>
              <div className="space-y-2">
                {stats.dist.map((d) => (
                  <BarRow key={d.label} left={d.label} count={d.count} total={distTotal} showPct />
                ))}
              </div>
              <p className="mt-2 text-2xs text-ink-400 dark:text-ink-500">
                词数 = {stats.latinWords} 个英文单词 + {stats.cjkChars} 个中日韩字符
              </p>
            </div>
            <div>
              <p className="section-label mb-2.5">Top 20 字符频率</p>
              {stats.top.length > 0 ? (
                <div className="space-y-2">
                  {stats.top.map((t) => (
                    <BarRow key={t.ch} left={t.ch} count={t.count} total={topMax} right={`${((t.count / stats.chars) * 100).toFixed(1)}%`} />
                  ))}
                </div>
              ) : (
                <p className="text-xs text-ink-400 dark:text-ink-500">无可统计的非空白字符</p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-xs text-ink-400 dark:text-ink-500">输入文本后在此显示统计结果</p>
        )}
      </div>

      <p className="mt-4 text-2xs leading-relaxed text-ink-400 dark:text-ink-500">
        字符按 Unicode 码点计数（emoji / 代理对计 1）；字节按 UTF-8 编码计（中文 3 字节）；
        频率条以榜内最大计数为满格，百分比按总字符数计，已排除空白与控制字符。
      </p>
    </Card>
  );
}
