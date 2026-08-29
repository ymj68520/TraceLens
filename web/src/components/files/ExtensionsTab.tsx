import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import Card, { CardHeader } from '../ui/Card';
import { LoadingBlock } from '../ui/Spinner';
import EmptyState from '../ui/EmptyState';
import { formatBytes } from '../../lib/utils';

interface ExtensionRow {
  extension?: string;
  count?: number;
  total_size?: number;
  [key: string]: unknown;
}

interface ExtensionsTabProps {
  data: unknown;
  loading: boolean;
}

export default function ExtensionsTab({ data, loading }: ExtensionsTabProps) {
  const rows = useMemo<ExtensionRow[]>(() => {
    const d = data as { extensions?: ExtensionRow[]; analysis?: ExtensionRow[] } | null;
    return d?.extensions ?? d?.analysis ?? [];
  }, [data]);

  const chartData = useMemo(
    () =>
      rows
        .slice(0, 15)
        .map((r) => ({ name: r.extension || '(无)', count: r.count ?? 0 })),
    [rows],
  );

  if (loading) return <LoadingBlock text="正在分析扩展名…" />;

  return (
    <div className="space-y-4">
      {chartData.length > 0 && (
        <Card>
          <CardHeader title="扩展名分布（Top 15）" />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8b9da2' }} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: '#8b9da2' }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 6, border: '1px solid #d6dddf' }}
                />
                <Bar dataKey="count" fill="#2e9b96" radius={[3, 3, 0, 0]} name="文件数" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <Card padded={false}>
        {rows.length === 0 ? (
          <EmptyState title="暂无扩展名统计数据" />
        ) : (
          <table className="table-shell">
            <thead>
              <tr>
                <th>扩展名</th>
                <th className="text-right">文件数</th>
                <th className="text-right">总大小</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.extension ?? i}>
                  <td className="font-mono text-xs">{row.extension || '(无)'}</td>
                  <td className="text-right tabular-nums">{row.count ?? 0}</td>
                  <td className="text-right font-mono text-xs">{formatBytes(Number(row.total_size ?? 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
