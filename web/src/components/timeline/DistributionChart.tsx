import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import type { DistributionRow } from '../../pages/Timeline';

const COLORS = {
  CREATED: '#2e9b96',
  MODIFIED: '#4f83cc',
  DELETED: '#d45b6a',
  OTHER: '#8b9da2',
};

export default function DistributionChart({ data }: { data: DistributionRow[] }) {
  return (
    <div className="card card-pad">
      <h3 className="card-title mb-3">活动分布</h3>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }} barCategoryGap="20%">
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: '#8b9da2' }}
              tickLine={false}
              axisLine={{ stroke: '#d6dddf' }}
              tickFormatter={(d: string) => d.slice(5)}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                borderRadius: 6,
                border: '1px solid #d6dddf',
                boxShadow: '0 4px 10px rgba(16,24,28,0.08)',
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />
            <Bar dataKey="CREATED" stackId="a" fill={COLORS.CREATED} name="创建" />
            <Bar dataKey="MODIFIED" stackId="a" fill={COLORS.MODIFIED} name="修改" />
            <Bar dataKey="DELETED" stackId="a" fill={COLORS.DELETED} name="删除" />
            <Bar dataKey="OTHER" stackId="a" fill={COLORS.OTHER} name="其他" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
