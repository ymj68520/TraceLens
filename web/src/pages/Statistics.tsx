import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getStatisticsOverview } from '../services/forensicsService';
import Card, { CardHeader } from '../components/ui/Card';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import { BarChart3 } from 'lucide-react';
import { errorMessage, formatBytes } from '../lib/utils';

interface StatRow {
  label: string;
  value: string | number;
}

function Row({ label, value }: StatRow) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-ink-100 dark:border-ink-800/60 last:border-0">
      <span className="text-xs text-ink-500 dark:text-ink-400">{label}</span>
      <span className="text-sm font-medium text-ink-900 dark:text-ink-100 tabular-nums">{value}</span>
    </div>
  );
}

export default function Statistics() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');

  const [statistics, setStatistics] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    getStatisticsOverview(taskId)
      .then((data) => setStatistics(data as Record<string, unknown>))
      .catch((err) => {
        setStatistics({ overview: {} });
        setError(errorMessage(err));
      })
      .finally(() => setLoading(false));
  }, [taskId]);

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<BarChart3 size={36} />}
          title="未选择任务"
          description="请先选择一个已完成的分析任务。"
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="card">
        <LoadingBlock text="正在加载统计…" />
      </div>
    );
  }

  const overview = (statistics?.overview ?? {}) as Record<string, unknown>;
  const filesList = statistics?.files_database_stats as Record<string, number>[] | undefined;
  const eventsList = statistics?.events_database_stats as Record<string, number>[] | undefined;
  const filesStats: Record<string, number> = filesList?.[0] ?? {};
  const eventsStats: Record<string, number> = eventsList?.[0] ?? {};

  return (
    <div className="space-y-4 max-w-5xl">
      {error && (
        <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="概览" />
          {Object.entries(overview).length === 0 ? (
            <EmptyState title="暂无概览数据" />
          ) : (
            Object.entries(overview).map(([k, v]) => (
              <Row key={k} label={k} value={typeof v === 'number' ? v.toLocaleString() : String(v)} />
            ))
          )}
        </Card>

        <Card>
          <CardHeader title="文件库统计" />
          {Object.keys(filesStats).length === 0 ? (
            <EmptyState title="暂无文件统计" />
          ) : (
            Object.entries(filesStats).map(([k, v]) => (
              <Row
                key={k}
                label={k}
                value={k.toLowerCase().includes('size') ? formatBytes(v) : Number(v).toLocaleString()}
              />
            ))
          )}
        </Card>

        <Card>
          <CardHeader title="事件库统计" />
          {Object.keys(eventsStats).length === 0 ? (
            <EmptyState title="暂无事件统计" />
          ) : (
            Object.entries(eventsStats).map(([k, v]) => (
              <Row key={k} label={k} value={Number(v).toLocaleString()} />
            ))
          )}
        </Card>
      </div>
    </div>
  );
}
