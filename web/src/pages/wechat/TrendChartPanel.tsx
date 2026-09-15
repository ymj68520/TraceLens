import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CalendarClock } from 'lucide-react';
import EmptyState from '../../components/ui/EmptyState';
import type { TimelineSummary } from './wechatUtils';

const MAX_POINTS = 60;

/** 活跃趋势：来自 /wechat/graph/timeline 的按日聚合。接口不可用时降级为空态。 */
export default function TrendChartPanel({ trend }: { trend: TimelineSummary | null }) {
  if (!trend) {
    return (
      <EmptyState
        className="flex-1"
        icon={<CalendarClock size={30} />}
        title="暂无时间线数据"
        description="时间线接口不可用或未返回可解析的消息分布字段。"
      />
    );
  }

  const data = trend.points.slice(-MAX_POINTS).map((p) => ({
    label: p.label.length > 5 ? p.label.slice(5) : p.label,
    消息数: p.count,
    full: p.label,
  }));

  return (
    <div className="flex-1 min-h-0 flex flex-col p-3 gap-2">
      <div className="flex items-center gap-2 shrink-0">
        <span className="section-label">按日消息量</span>
        <span className="text-2xs text-ink-400 truncate">
          峰值 <span className="font-mono">{trend.peak.label}</span> · {trend.peak.count} 条
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: '#8b9da2' }}
              tickLine={false}
              axisLine={{ stroke: '#d6dddf' }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#8b9da2' }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                borderRadius: 6,
                border: '1px solid #d6dddf',
                boxShadow: '0 4px 10px rgba(16,24,28,0.08)',
              }}
              formatter={(value) => [`${value} 条`, '消息']}
              labelFormatter={(label, payload) => String(payload?.[0]?.payload?.full ?? label)}
            />
            <Area
              type="monotone"
              dataKey="消息数"
              stroke="#17aaa8"
              strokeWidth={1.5}
              fill="rgba(23,170,168,0.15)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
