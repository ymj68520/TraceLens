import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface StatCardItem {
  icon: LucideIcon;
  tone: string;
  label: string;
  value: string;
  sub?: string;
}

/** 统计摘要卡：消息总数 / 联系人数 / 会话关系 / 活跃峰值。字段缺失时展示「—」与原因。 */
export default function StatsCards({ cards }: { cards: StatCardItem[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <div key={c.label} className="card card-pad flex items-center gap-3.5 py-4">
            <span className={cn('hidden sm:flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', c.tone)}>
              <Icon size={19} strokeWidth={1.9} />
            </span>
            <div className="min-w-0">
              <p className="section-label">{c.label}</p>
              <p className="text-lg font-semibold text-ink-900 dark:text-white tabular-nums truncate" title={c.value}>
                {c.value}
              </p>
              {c.sub && <p className="text-2xs text-ink-400 truncate">{c.sub}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
