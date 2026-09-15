import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { OssRow } from './ossUtils';

/** Compact bar chart of the top extensions by object count (stats tab). */
export default function OssExtensionChart({ rows }: { rows: OssRow[] }) {
  const data = useMemo(
    () =>
      rows
        .slice()
        .sort((a, b) => Number(b.count ?? 0) - Number(a.count ?? 0))
        .slice(0, 10)
        .map((r) => ({ name: String(r.extension ?? '(无)'), count: Number(r.count ?? 0) })),
    [rows],
  );

  if (data.length === 0) return null;

  return (
    <div className="px-5 pt-4">
      <p className="section-label mb-2">对象数 Top 10</p>
      <div className="h-44 border border-ink-100 dark:border-ink-800 rounded-md px-2 pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8b9da2' }} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: '#8b9da2' }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 6, border: '1px solid #d6dddf' }} />
            <Bar dataKey="count" fill="#17aaa8" radius={[3, 3, 0, 0]} name="对象数" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
