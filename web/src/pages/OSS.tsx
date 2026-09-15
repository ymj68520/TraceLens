import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BarChart3, Cloud, ListTree, Play, ScrollText } from 'lucide-react';
import {
  getObjects,
  getAccessLogs,
  getSummary,
  getExtensionStats,
  startAnalysis,
  pollAnalysisStatus,
} from '../services/ossService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { useToast } from '../components/ui/Toast';
import { errorMessage } from '../lib/utils';
import { PageHeader, Segmented, StatStrip, type StatItem } from '../components/ui/PageScaffold';
import { useUrlState } from '../hooks/useUrlState';
import OssTablePanel from './oss/OssTablePanel';
import { extractRows, isOssTab, type OssRow, type OssTab } from './oss/ossUtils';

type OssTabMeta = { key: OssTab; label: string; Icon: typeof Cloud };

const TABS: OssTabMeta[] = [
  { key: 'objects', label: '对象列表', Icon: ListTree },
  { key: 'logs', label: '访问日志', Icon: ScrollText },
  { key: 'summary', label: '摘要', Icon: Cloud },
  { key: 'stats', label: '统计', Icon: BarChart3 },
];

interface OssDatasets {
  objects: OssRow[];
  logs: OssRow[];
  stats: OssRow[];
  summary: OssRow;
}

const EMPTY_DATASETS: OssDatasets = { objects: [], logs: [], stats: [], summary: {} };

export default function OSS() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  // Active tab survives reloads and shareable links via the URL query.
  const [tabParam, setTabParam] = useUrlState('tab', 'objects');
  const activeTab: OssTab = isOssTab(tabParam) ? tabParam : 'objects';

  // All four endpoints load up front so every tab chip can show its row count.
  const [datasets, setDatasets] = useState<OssDatasets>(EMPTY_DATASETS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const [objects, logs, summary, stats] = await Promise.all([
        getObjects(taskId),
        getAccessLogs(taskId),
        getSummary(taskId),
        getExtensionStats(taskId),
      ]);
      setDatasets({
        objects: extractRows(objects, 'objects', 'items'),
        logs: extractRows(logs, 'logs', 'items'),
        stats: extractRows(stats, 'stats', 'extensions', 'items'),
        summary: (summary ?? {}) as OssRow,
      });
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      setDatasets(EMPTY_DATASETS);
      toast.error(`OSS 数据加载失败：${msg}`);
    } finally {
      setLoading(false);
    }
    // toast identity is not stable; keeping it out avoids reload loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleStartAnalysis = async () => {
    if (!taskId) return;
    setAnalyzing(true);
    try {
      const res = (await startAnalysis(taskId)) as { job_id: string };
      toast.success('OSS 分析已启动');
      await pollAnalysisStatus(res.job_id, undefined, 2000);
      toast.success('OSS 分析完成');
      void load();
    } catch (err) {
      toast.error(`分析失败：${errorMessage(err)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const chips = useMemo<StatItem[]>(
    () => [
      {
        label: '对象',
        value: datasets.objects.length,
        active: activeTab === 'objects',
        onClick: () => setTabParam('objects'),
      },
      {
        label: '访问日志',
        value: datasets.logs.length,
        active: activeTab === 'logs',
        onClick: () => setTabParam('logs'),
      },
      {
        label: '摘要字段',
        value: Object.keys(datasets.summary).length,
        active: activeTab === 'summary',
        onClick: () => setTabParam('summary'),
      },
      {
        label: '扩展名',
        value: datasets.stats.length,
        active: activeTab === 'stats',
        onClick: () => setTabParam('stats'),
      },
    ],
    [datasets, activeTab, setTabParam],
  );

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState icon={<Cloud size={36} />} title="未选择任务" description="请选择一个包含 OSS 数据的任务。" />
      </div>
    );
  }

  const rows =
    activeTab === 'objects'
      ? datasets.objects
      : activeTab === 'logs'
        ? datasets.logs
        : datasets.stats;

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={Cloud}
        tone="sky"
        title="OSS 分析"
        subtitle="对象存储取证数据解析"
        actions={
          <Button size="sm" variant="primary" onClick={handleStartAnalysis} disabled={analyzing}>
            <Play size={13} />
            {analyzing ? '分析中…' : '启动 OSS 分析'}
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          options={TABS.map(({ key, label, Icon }) => ({ value: key, label, icon: Icon }))}
          value={activeTab}
          onChange={setTabParam}
        />
        <StatStrip stats={chips} className="ml-auto" />
      </div>

      <Card padded={false}>
        <OssTablePanel
          key={activeTab}
          tab={activeTab}
          taskId={taskId}
          rows={rows}
          summary={activeTab === 'summary' ? datasets.summary : null}
          loading={loading}
          error={error}
          onRetry={() => void load()}
        />
      </Card>
    </div>
  );
}
