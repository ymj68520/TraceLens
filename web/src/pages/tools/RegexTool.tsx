import { useMemo, useState } from 'react';
import { Regex as RegexIcon, Trash2 } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { cn } from '../../lib/utils';
import { useCopy, useDebouncedValue } from './shared';

/* ---------------------------------------------------------------------------
 * 正则测试：实时高亮全部匹配 + 分组捕获列表 + 匹配计数。
 * 无效正则捕获异常显示错误提示；匹配数设上限，防止灾难性回溯拖死页面。
 * ------------------------------------------------------------------------- */

const FLAG_DEFS = [
  { key: 'g', desc: '全局' },
  { key: 'i', desc: '忽略大小写' },
  { key: 'm', desc: '多行 ^ $' },
  { key: 's', desc: 'dotAll . 换行' },
  { key: 'u', desc: 'Unicode' },
] as const;

type FlagKey = (typeof FLAG_DEFS)[number]['key'];

interface RegexGroup {
  label: string;
  value: string | null;
}

interface RegexHit {
  index: number;
  text: string;
  groups: RegexGroup[];
}

const MAX_HITS = 1000;
const MAX_SCAN = 20000;

interface CompileResult {
  re: RegExp | null;
  error: string;
}

function compile(pattern: string, flags: string): CompileResult {
  if (!pattern) return { re: null, error: '' };
  try {
    return { re: new RegExp(pattern, flags), error: '' };
  } catch (e) {
    return { re: null, error: e instanceof Error ? e.message : String(e) };
  }
}

function runRegex(re: RegExp, text: string): { hits: RegexHit[]; truncated: boolean } {
  // 用全新实例跑匹配，避免共享 lastIndex 造成 useMemo 重复执行结果漂移
  const rx = new RegExp(re.source, re.flags);
  const hits: RegexHit[] = [];
  let truncated = false;
  let guard = 0;
  while (guard < MAX_SCAN) {
    guard += 1;
    const m = rx.exec(text);
    if (m === null) break;
    const groups: RegexGroup[] = [];
    for (let i = 1; i < m.length; i += 1) groups.push({ label: `$${i}`, value: m[i] ?? null });
    for (const [name, value] of Object.entries(m.groups ?? {})) groups.push({ label: `$<${name}>`, value });
    hits.push({ index: m.index, text: m[0], groups });
    if (!rx.global) break;
    if (m[0].length === 0) rx.lastIndex += 1; // 零宽匹配手动前进，防死循环
    if (hits.length >= MAX_HITS) {
      truncated = true;
      break;
    }
  }
  return { hits, truncated };
}

export default function RegexTool() {
  const copy = useCopy();
  const [pattern, setPattern] = useState('');
  const [text, setText] = useState('');
  const [flags, setFlags] = useState<Record<FlagKey, boolean>>({ g: true, i: false, m: false, s: false, u: false });

  const debouncedPattern = useDebouncedValue(pattern, 150);
  const debouncedText = useDebouncedValue(text, 150);
  const flagsStr = FLAG_DEFS.map((f) => (flags[f.key] ? f.key : '')).join('');

  const { re, error } = useMemo(() => compile(debouncedPattern, flagsStr), [debouncedPattern, flagsStr]);
  const { hits, truncated } = useMemo(
    () => (re && debouncedText ? runRegex(re, debouncedText) : { hits: [], truncated: false }),
    [re, debouncedText],
  );

  /* 高亮分段：由命中区间切分文本（零宽匹配不参与高亮） */
  const segments = useMemo(() => {
    if (hits.length === 0) return null;
    const parts: Array<{ text: string; hit: boolean }> = [];
    let cursor = 0;
    for (const h of hits) {
      if (h.text.length === 0 || h.index < cursor) continue;
      if (h.index > cursor) parts.push({ text: debouncedText.slice(cursor, h.index), hit: false });
      parts.push({ text: h.text, hit: true });
      cursor = h.index + h.text.length;
    }
    if (cursor < debouncedText.length) parts.push({ text: debouncedText.slice(cursor), hit: false });
    return parts;
  }, [hits, debouncedText]);

  const clearAll = () => {
    setPattern('');
    setText('');
    setFlags({ g: true, i: false, m: false, s: false, u: false });
  };

  return (
    <Card>
      <CardHeader
        title="正则测试"
        subtitle="实时高亮匹配、列出分组捕获，全部在浏览器本地执行"
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              disabled={hits.length === 0}
              onClick={() => void copy(hits.map((h) => h.text).join('\n'), '全部匹配')}
            >
              复制全部匹配
            </Button>
            <Button variant="ghost" size="sm" onClick={clearAll}>
              <Trash2 size={13} />
              清空
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div>
          <label className="field-label" htmlFor="regex-pattern">正则表达式</label>
          <input
            id="regex-pattern"
            type="text"
            className={cn('input font-mono', error && 'border-rose-400 dark:border-rose-500/60')}
            placeholder="例如 \\d{4}-\\d{2}-\\d{2}"
            value={pattern}
            spellCheck={false}
            onChange={(e) => setPattern(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1.5 sm:pb-2">
          {FLAG_DEFS.map((f) => (
            <label key={f.key} className="flex cursor-pointer items-center gap-1.5 text-xs text-ink-600 dark:text-ink-300">
              <input
                type="checkbox"
                className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                checked={flags[f.key]}
                onChange={(e) => setFlags((prev) => ({ ...prev, [f.key]: e.target.checked }))}
              />
              <span className="font-mono">{f.key}</span>
              <span className="text-2xs text-ink-400 dark:text-ink-500">{f.desc}</span>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <p className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 font-mono text-2xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          正则无效：{error}
        </p>
      )}

      <div className="mt-3">
        <label className="field-label" htmlFor="regex-text">测试文本</label>
        <textarea
          id="regex-text"
          className="input font-mono text-xs leading-relaxed"
          rows={5}
          spellCheck={false}
          placeholder="粘贴待匹配文本"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>

      {/* 高亮预览 */}
      <div className="mt-3">
        <p className="section-label mb-1.5">高亮预览</p>
        <div className="max-h-56 overflow-auto rounded-md border border-ink-200 bg-ink-50 px-3 py-2.5 dark:border-ink-800 dark:bg-ink-900">
          {error ? (
            <span className="text-xs text-ink-400 dark:text-ink-500">修正正则后显示高亮</span>
          ) : segments ? (
            <span className="break-words font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-700 dark:text-ink-200">
              {segments.map((seg, i) =>
                seg.hit ? (
                  <mark
                    key={i}
                    className="rounded-sm bg-accent-200/70 px-0.5 text-ink-900 dark:bg-accent-500/30 dark:text-accent-100"
                  >
                    {seg.text}
                  </mark>
                ) : (
                  <span key={i}>{seg.text}</span>
                ),
              )}
            </span>
          ) : (
            <span className="text-xs text-ink-400 dark:text-ink-500">输入正则与文本后在此高亮匹配</span>
          )}
        </div>
      </div>

      {/* 匹配列表 */}
      <div className="mt-4 flex items-center justify-between gap-2">
        <p className="section-label">
          匹配列表
          <span className="ml-2 font-mono text-2xs normal-case tracking-normal tabular-nums text-ink-400 dark:text-ink-500">
            {hits.length}
            {truncated ? '+' : ''} 处{!flags.g && re ? '（未勾选 g，仅首个）' : ''}
          </span>
        </p>
        <RegexIcon size={13} className="shrink-0 text-ink-300 dark:text-ink-600" />
      </div>
      {hits.length > 0 ? (
        <ul className="mt-1.5 max-h-64 divide-y divide-ink-100 overflow-auto rounded-lg border border-ink-100 dark:divide-ink-800/60 dark:border-ink-800/60">
          {hits.map((h, i) => (
            <li key={`${h.index}-${i}`} className="px-3 py-2">
              <div className="flex items-baseline gap-2 text-xs">
                <span className="w-12 shrink-0 font-mono text-2xs tabular-nums text-ink-400 dark:text-ink-500">#{i + 1}</span>
                <span className="shrink-0 font-mono text-2xs tabular-nums text-ink-400 dark:text-ink-500">@{h.index}</span>
                <span className="min-w-0 break-all font-mono text-ink-800 dark:text-ink-100">
                  {h.text || <span className="text-ink-300 dark:text-ink-600">（零宽匹配）</span>}
                </span>
              </div>
              {h.groups.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1 pl-14">
                  {h.groups.map((g, gi) => (
                    <span
                      key={gi}
                      className={cn(
                        'chip max-w-full break-all font-mono',
                        g.value === null
                          ? 'bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500'
                          : 'bg-accent-50 text-accent-700 dark:bg-accent-500/10 dark:text-accent-300',
                      )}
                    >
                      {g.label}={g.value === null ? '未捕获' : g.value}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-xs text-ink-400 dark:text-ink-500">暂无匹配</p>
      )}
      {truncated && (
        <p className="mt-1.5 text-2xs text-amber-600 dark:text-amber-400">匹配数超过 {MAX_HITS}，列表已截断，计数为 {MAX_HITS}+。</p>
      )}
    </Card>
  );
}
