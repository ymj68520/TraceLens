import { cn } from '../../lib/utils';
import { FOCUS_RING, MATCH_RING, type TypeStat } from './kgUtils';

interface GraphLegendProps {
  /** 当前图谱中出现的实体类型（节点配色图例）。 */
  typeStats: TypeStat[];
  className?: string;
}

const LINK_SAMPLE = 'rgba(139,157,162,0.6)';
const MAX_TYPE_ITEMS = 8;

/** 图例面板：节点类型配色、关系边与高亮环说明。 */
export default function GraphLegend({ typeStats, className }: GraphLegendProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2', className)}>
      <span className="section-label">图例</span>
      {typeStats.slice(0, MAX_TYPE_ITEMS).map((t) => (
        <span key={t.key} className="inline-flex items-center gap-1.5 text-2xs text-ink-500 dark:text-ink-400">
          <span aria-hidden className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: t.color }} />
          {t.label}
          <span className="font-mono tabular-nums text-ink-400 dark:text-ink-500">{t.count}</span>
        </span>
      ))}
      {typeStats.length > MAX_TYPE_ITEMS && (
        <span className="text-2xs text-ink-400 dark:text-ink-500">等 {typeStats.length} 类</span>
      )}
      <span className="inline-flex items-center gap-1.5 text-2xs text-ink-500 dark:text-ink-400">
        <span aria-hidden className="h-0.5 w-4 rounded-full shrink-0" style={{ backgroundColor: LINK_SAMPLE }} />
        关系（箭头指向目标实体）
      </span>
      <span className="inline-flex items-center gap-1.5 text-2xs text-ink-500 dark:text-ink-400">
        <span aria-hidden className="h-2 w-2 rounded-full shrink-0 border-2" style={{ borderColor: FOCUS_RING }} />
        当前定位
      </span>
      <span className="inline-flex items-center gap-1.5 text-2xs text-ink-500 dark:text-ink-400">
        <span aria-hidden className="h-2 w-2 rounded-full shrink-0 border-2" style={{ borderColor: MATCH_RING }} />
        搜索命中
      </span>
    </div>
  );
}
