import { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { useToast } from '../../components/ui/Toast';
import { cn } from '../../lib/utils';

/* ---------------------------------------------------------------------------
 * 小工具页共享件：输入防抖、剪贴板复制、统一结果行。
 * 全部纯前端，无网络请求。
 * ------------------------------------------------------------------------- */

/** 输入防抖：给重计算（哈希 / 正则 / 统计）留出输入喘息空间。 */
export function useDebouncedValue<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

/** 剪贴板复制 + sonner toast 反馈；非安全上下文回退 execCommand。 */
export function useCopy(): (text: string, label?: string) => Promise<void> {
  const toast = useToast();
  return async (text, label = '内容') => {
    const ok = () => toast.success(`${label}已复制到剪贴板`);
    try {
      await navigator.clipboard.writeText(text);
      ok();
    } catch {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        ok();
      } catch {
        toast.error('复制失败，浏览器未授权剪贴板访问');
      }
    }
  };
}

/** 图标复制按钮：复制成功后短暂变为对勾。 */
export function CopyButton({ value, label, className }: { value: string; label?: string; className?: string }) {
  const copy = useCopy();
  const [copied, setCopied] = useState(false);
  const target = label ?? '结果';

  const handleCopy = () => {
    void copy(value, target);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={copied ? '已复制' : `复制${target}`}
      title={copied ? '已复制' : '复制'}
      className={cn(
        'shrink-0 rounded p-1.5 text-ink-400 transition-colors',
        'hover:bg-ink-100 hover:text-ink-600 dark:hover:bg-ink-800 dark:hover:text-ink-200',
        copied && 'text-emerald-600 dark:text-emerald-400',
        className,
      )}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </button>
  );
}

/** 标签 + mono 值 + 复制按钮的统一结果行。 */
export function ResultRow({
  label,
  note,
  value,
  emptyValue = '—',
}: {
  label: string;
  note?: string;
  value: string;
  emptyValue?: string;
}) {
  const has = value.length > 0;
  return (
    <div className="flex items-center gap-3 border-b border-ink-100 py-[7px] last:border-b-0 dark:border-ink-800/60">
      <span className="flex w-24 shrink-0 flex-col">
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">{label}</span>
        {note && <span className="text-2xs text-ink-300 dark:text-ink-600">{note}</span>}
      </span>
      <span
        className={cn(
          'min-w-0 flex-1 break-all font-mono text-xs',
          has ? 'text-ink-800 dark:text-ink-100' : 'select-none text-ink-300 dark:text-ink-600',
        )}
      >
        {has ? value : emptyValue}
      </span>
      {has ? <CopyButton value={value} label={`${label} 值`} /> : <span className="w-7 shrink-0" aria-hidden />}
    </div>
  );
}
