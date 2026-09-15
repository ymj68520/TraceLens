import { useMemo, useState } from 'react';
import { Search as SearchIcon, X } from 'lucide-react';
import { matchNode, nodeName, typeMeta, type KgNode } from './kgUtils';

interface NodeSearchPanelProps {
  /** 在可见节点范围内搜索。 */
  nodes: KgNode[];
  value: string;
  onChange: (v: string) => void;
  onSelect: (node: KgNode) => void;
}

const MAX_RESULTS = 10;

/**
 * 图谱节点即时搜索：输入即按名称/ID 过滤并高亮画布命中节点，
 * 下拉列表可点击定位（定位逻辑由父组件 centerAt/zoom 完成）。
 */
export default function NodeSearchPanel({ nodes, value, onChange, onSelect }: NodeSearchPanelProps) {
  const [open, setOpen] = useState(false);

  const matches = useMemo(
    () => (value.trim() ? nodes.filter((n) => matchNode(n, value)) : []),
    [nodes, value],
  );
  const results = matches.slice(0, MAX_RESULTS);

  return (
    <div className="relative">
      <span
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 dark:text-ink-500"
      >
        <SearchIcon size={13} />
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        placeholder="搜索节点并定位…"
        aria-label="搜索节点"
        className="input w-64 pl-8 pr-7 py-1.5 text-xs"
      />
      {value && (
        <button
          type="button"
          aria-label="清空搜索"
          onClick={() => {
            onChange('');
            setOpen(false);
          }}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
        >
          <X size={12} />
        </button>
      )}
      {open && value.trim() && (
        <div className="absolute left-0 top-full mt-1 z-30 w-80 max-h-72 overflow-y-auto card shadow-pop p-1">
          {results.length === 0 ? (
            <p className="px-3 py-4 text-center text-2xs text-ink-400 dark:text-ink-500">
              未找到名称包含「{value.trim()}」的节点
            </p>
          ) : (
            <>
              {results.map((n) => {
                const meta = typeMeta(n.type);
                return (
                  <button
                    key={n.id}
                    type="button"
                    // mousedown 先于 input 的 blur 触发，避免下拉提前关闭
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      onSelect(n);
                      setOpen(false);
                    }}
                    className="w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left hover:bg-accent-50 dark:hover:bg-accent-500/10 transition-colors"
                  >
                    <span aria-hidden className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: meta.color }} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium text-ink-800 dark:text-ink-100 truncate">
                        {nodeName(n)}
                      </span>
                      <span className="block text-2xs text-ink-400 dark:text-ink-500 truncate font-mono">{n.id}</span>
                    </span>
                    <span className="chip bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400 shrink-0">
                      {meta.label}
                    </span>
                  </button>
                );
              })}
              {matches.length > results.length && (
                <p className="px-3 py-1.5 text-2xs text-ink-400 dark:text-ink-500">
                  仅显示前 {results.length} 条，共 {matches.length} 个命中
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
