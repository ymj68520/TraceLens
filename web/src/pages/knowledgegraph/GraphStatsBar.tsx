import { Boxes, GitBranch, Network } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { TypeStat } from './kgUtils';

interface GraphStatsBarProps {
  nodeTotal: number;
  linkTotal: number;
  typeStats: TypeStat[];
  activeTypes: string[];
  onToggleType: (key: string) => void;
}

/** 节点/边统计卡 + 实体类型分布（颜色按类型，点击 chip 过滤图谱显示）。 */
export default function GraphStatsBar({
  nodeTotal,
  linkTotal,
  typeStats,
  activeTypes,
  onToggleType,
}: GraphStatsBarProps) {
  const activeSet = new Set(activeTypes);
  const filtering = activeTypes.length > 0;
  const maxCount = typeStats.reduce((m, t) => Math.max(m, t.count), 1);
  const avgDegree = nodeTotal > 0 ? (linkTotal / nodeTotal).toFixed(1) : '0';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
      <div className="card card-pad flex items-center gap-3.5 py-4">
        <span className="hidden sm:flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300">
          <Network size={19} strokeWidth={1.9} />
        </span>
        <div className="min-w-0">
          <p className="section-label">节点总数</p>
          <p className="text-lg font-semibold text-ink-900 dark:text-white tabular-nums">{nodeTotal}</p>
          <p className="text-2xs text-ink-400 truncate">{typeStats.length} 种实体类型</p>
        </div>
      </div>

      <div className="card card-pad flex items-center gap-3.5 py-4">
        <span className="hidden sm:flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-100 dark:bg-violet-500/15 text-violet-700 dark:text-violet-300">
          <GitBranch size={19} strokeWidth={1.9} />
        </span>
        <div className="min-w-0">
          <p className="section-label">关系总数</p>
          <p className="text-lg font-semibold text-ink-900 dark:text-white tabular-nums">{linkTotal}</p>
          <p className="text-2xs text-ink-400 truncate">平均每节点 {avgDegree} 条</p>
        </div>
      </div>

      <div className="card card-pad py-4 sm:col-span-2">
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <p className="section-label flex items-center gap-1.5">
            <Boxes size={13} className="text-ink-400 dark:text-ink-500" /> 实体类型分布
          </p>
          {filtering && (
            <span className="chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
              已选 {activeTypes.length} 类
            </span>
          )}
        </div>
        {typeStats.length === 0 ? (
          <p className="text-2xs text-ink-400 py-2">暂无节点数据</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {typeStats.map((t) => {
              const active = activeSet.has(t.key);
              const dimmed = filtering && !active;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => onToggleType(t.key)}
                  aria-pressed={active}
                  title={`按「${t.label}」过滤图谱`}
                  className={cn(
                    'rounded-lg border px-2 py-1.5 min-w-[104px] text-left transition-all duration-150 active:scale-[0.97]',
                    active
                      ? 'border-accent-400 bg-accent-50 dark:border-accent-500/40 dark:bg-accent-500/10'
                      : 'border-ink-200/80 bg-white dark:border-ink-800 dark:bg-ink-925 hover:border-ink-300 dark:hover:border-ink-700',
                    dimmed && 'opacity-50',
                  )}
                >
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: t.color }} />
                    <span
                      className="text-2xs font-medium text-ink-700 dark:text-ink-200 truncate max-w-[88px]"
                      title={t.label}
                    >
                      {t.label}
                    </span>
                    <span className="ml-auto font-mono text-2xs tabular-nums text-ink-500 dark:text-ink-400">
                      {t.count}
                    </span>
                  </span>
                  <span aria-hidden className="mt-1 block h-1 rounded-full bg-ink-100 dark:bg-ink-800 overflow-hidden">
                    <span
                      className="block h-full rounded-full"
                      style={{ width: `${Math.max(6, (t.count / maxCount) * 100)}%`, backgroundColor: t.color }}
                    />
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
