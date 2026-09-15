import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { EVENT_TYPE_HEX } from './eventTypes';

export interface DistributionRow {
  date: string;
  CREATED: number;
  MODIFIED: number;
  DELETED: number;
  OTHER: number;
}

const AXIS_NEUTRAL = '#8b9da2';

export default function DistributionChart({ data }: { data: DistributionRow[] }) {
  return (
    <div className="card card-pad">
      <h3 className="card-title mb-3">活动分布</h3>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }} barCategoryGap="20%">
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: AXIS_NEUTRAL }}
              tickLine={false}
              axisLine={{ stroke: AXIS_NEUTRAL, strokeOpacity: 0.35 }}
              tickFormatter={(d: string) => d.slice(5)}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                borderRadius: 6,
                border: '1px solid rgba(139,157,162,0.4)',
                boxShadow: '0 4px 10px rgba(16,24,28,0.08)',
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />
            <Bar dataKey="CREATED" stackId="a" fill={EVENT_TYPE_HEX.CREATED} name="创建" />
            <Bar dataKey="MODIFIED" stackId="a" fill={EVENT_TYPE_HEX.MODIFIED} name="修改" />
            <Bar dataKey="DELETED" stackId="a" fill={EVENT_TYPE_HEX.DELETED} name="删除" />
            <Bar dataKey="OTHER" stackId="a" fill={EVENT_TYPE_HEX.OTHER} name="其他" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
