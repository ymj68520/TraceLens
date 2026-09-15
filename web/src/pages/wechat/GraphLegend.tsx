import { cn } from '../../lib/utils';

interface LegendItem {
  color: string;
  label: string;
  count?: number;
  line?: boolean;
}

interface GraphLegendProps {
  ownerPresent: boolean;
  contactCount: number;
  groupNodeCount: number;
  dmEdgeCount: number;
  groupEdgeCount: number;
  className?: string;
}

/** 图谱图例：节点/边配色说明 + 计数徽章。群聊元素为 0 时不显示对应条目。 */
export default function GraphLegend({
  ownerPresent,
  contactCount,
  groupNodeCount,
  dmEdgeCount,
  groupEdgeCount,
  className,
}: GraphLegendProps) {
  const items: LegendItem[] = [
    ...(ownerPresent ? [{ color: '#0d8a89', label: '机主' }] : []),
    { color: '#17aaa8', label: '联系人', count: contactCount },
    ...(groupNodeCount > 0 ? [{ color: '#38bdf8', label: '群聊', count: groupNodeCount }] : []),
    { color: 'rgba(23,170,168,0.4)', label: '双人会话', count: dmEdgeCount, line: true },
    ...(groupEdgeCount > 0 ? [{ color: 'rgba(56,189,248,0.5)', label: '群会话', count: groupEdgeCount, line: true }] : []),
    { color: '#f59e0b', label: '当前选中' },
  ];

  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2', className)}>
      <span className="section-label">图例</span>
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5 text-2xs text-ink-500 dark:text-ink-400">
          {item.line ? (
            <span aria-hidden className="h-0.5 w-4 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
          ) : (
            <span aria-hidden className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
          )}
          {item.label}
          {item.count != null && <span className="font-mono tabular-nums text-ink-400 dark:text-ink-500">{item.count}</span>}
        </span>
      ))}
      <span className="text-2xs text-ink-300 dark:text-ink-600 ml-auto hidden md:inline">连线粗细代表消息量</span>
    </div>
  );
}
