import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Database,
  MessageSquare,
  Package,
  RefreshCw,
  Smartphone,
  Sparkles,
} from 'lucide-react';
import {
  getAndroidLlmSummary,
  getMiuiDbInventory,
  getMiuiInstalledApps,
  getMiuiOverview,
  getMiuiQqntArtifacts,
  getMiuiQqntOverview,
  getMiuiQqntRecords,
  getMiuiWechatArtifacts,
  getMiuiWechatOverview,
  getMiuiWechatRecords,
} from '../services/forensicsService';
import Button from '../components/ui/Button';
import Card from '../components/ui/Card';
import EmptyState from '../components/ui/EmptyState';
import { PageHeader, Segmented } from '../components/ui/PageScaffold';
import { useToast } from '../components/ui/Toast';
import { useUrlState } from '../hooks/useUrlState';
import { downloadCSV } from '../lib/exportUtils';
import { errorMessage } from '../lib/utils';
import {
  cellText,
  extractKv,
  extractRows,
  KeyValueGrid,
  RecordTableSection,
  type Row,
} from './android/RecordTable';
import { RecordDetailDrawer } from './android/RecordDetailDrawer';
import { ANDROID_FIELD_LABELS } from './android/labels';
import AppsTab from './android/AppsTab';
import DbTab from './android/DbTab';
import CommTab, { type CommBundle } from './android/CommTab';

type AndroidTab = 'overview' | 'apps' | 'db' | 'qqnt' | 'wechat' | 'llm';

const ANDROID_TABS: { key: AndroidTab; label: string; Icon: typeof Smartphone }[] = [
  { key: 'overview', label: '备份概览', Icon: Smartphone },
  { key: 'apps', label: '已安装应用', Icon: Package },
  { key: 'db', label: '数据库清单', Icon: Database },
  { key: 'qqnt', label: 'QQ/NT', Icon: MessageSquare },
  { key: 'wechat', label: '微信', Icon: MessageSquare },
  { key: 'llm', label: 'AI 摘要', Icon: Sparkles },
];

const ANDROID_TAB_KEYS = ANDROID_TABS.map((t) => t.key);

const EMPTY_COPY: Record<AndroidTab, { title: string; description: string }> = {
  overview: {
    title: '暂无备份概览数据',
    description: '该任务尚未生成 MIUI 备份概览，请确认任务使用 MIUI 备份源并已完成分析。',
  },
  apps: {
    title: '暂无应用数据',
    description: '该 MIUI 备份中未解析到已安装应用列表，请确认备份包含应用数据。',
  },
  db: {
    title: '暂无数据库清单',
    description: '该 MIUI 备份中未发现应用数据库，请确认备份内容完整。',
  },
  qqnt: {
    title: '暂无 QQ/NT 数据',
    description: '该任务尚未解析到 QQ/NT 取证数据，请确认备份中包含 QQ/NT 应用数据。',
  },
  wechat: {
    title: '暂无微信数据',
    description: '该任务尚未解析到微信取证数据，请确认备份中包含微信应用数据。',
  },
  llm: {
    title: '暂无 AI 摘要',
    description: '该任务尚未生成安卓取证的 AI 分析摘要。',
  },
};

export default function Android() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const toast = useToast();

  // Tab persisted to the URL so views survive reloads and are shareable.
  const [tabParam, setTabParam] = useUrlState('tab', 'overview');
  const activeTab: AndroidTab = (ANDROID_TAB_KEYS as string[]).includes(tabParam)
    ? (tabParam as AndroidTab)
    : 'overview';

  const [bundles, setBundles] = useState<Partial<Record<AndroidTab, unknown>>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailRow, setDetailRow] = useState<Row | null>(null);

  const load = useCallback(
    async (tab: AndroidTab) => {
      if (!taskId) return;
      setLoading(true);
      setError(null);
      try {
        switch (tab) {
          case 'overview': {
            const ov = await getMiuiOverview(taskId);
            setBundles((d) => ({ ...d, overview: ov }));
            break;
          }
          case 'apps': {
            const apps = await getMiuiInstalledApps(taskId);
            setBundles((d) => ({ ...d, apps }));
            break;
          }
          case 'db': {
            const db = await getMiuiDbInventory(taskId);
            setBundles((d) => ({ ...d, db }));
            break;
          }
          case 'qqnt': {
            const [ov, artifacts, records] = await Promise.all([
              getMiuiQqntOverview(taskId),
              getMiuiQqntArtifacts(taskId),
              getMiuiQqntRecords(taskId),
            ]);
            setBundles((d) => ({ ...d, qqnt: { overview: ov, artifacts, records } }));
            break;
          }
          case 'wechat': {
            const [ov, artifacts, records] = await Promise.all([
              getMiuiWechatOverview(taskId),
              getMiuiWechatArtifacts(taskId),
              getMiuiWechatRecords(taskId),
            ]);
            setBundles((d) => ({ ...d, wechat: { overview: ov, artifacts, records } }));
            break;
          }
          case 'llm': {
            const llm = await getAndroidLlmSummary(taskId);
            setBundles((d) => ({ ...d, llm }));
            break;
          }
        }
      } catch (err) {
        const msg = errorMessage(err);
        setError(msg);
        toast.error(`安卓取证数据加载失败：${msg}`);
      } finally {
        setLoading(false);
      }
      },
      // toast identity is stable enough; keeping it out avoids reload loops.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [taskId],
  );

  useEffect(() => {
    if (taskId) void load(activeTab);
  }, [taskId, activeTab, load]);

  const handleRetry = () => {
    if (taskId) void load(activeTab);
  };

  const activeBundle = bundles[activeTab];
  // Cached data keeps rendering while a refresh is in flight; skeletons and
  // error states only take over when there is nothing to show yet.
  const showLoading = loading && activeBundle === undefined;
  const showError = !showLoading && error !== null && activeBundle === undefined ? error : null;

  const overviewEntries = useMemo(() => extractKv(bundles.overview), [bundles.overview]);
  const apps = useMemo(() => extractRows(bundles.apps), [bundles.apps]);
  const databases = useMemo(() => extractRows(bundles.db), [bundles.db]);
  const llmEntries = useMemo(() => extractKv(bundles.llm), [bundles.llm]);

  const exportKvCsv = (entries: [string, unknown][], tab: AndroidTab) => {
    if (!taskId) return;
    if (entries.length === 0) {
      toast.info('当前没有可导出的数据');
      return;
    }
    downloadCSV(
      entries.map(([k, v]) => ({ key: k, value: cellText(v) })),
      `android-${tab}-${taskId.slice(0, 8)}.csv`,
      [
        { key: 'key', label: '字段' },
        { key: 'value', label: '值' },
      ],
    );
    toast.success(`已导出 ${entries.length} 个字段到 CSV`);
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<Smartphone size={36} />}
          title="未选择任务"
          description="请选择一个 MIUI 备份分析任务。"
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={Smartphone}
        tone="emerald"
        title="安卓取证"
        subtitle="MIUI 备份解析与应用数据分析"
        actions={
          <Button variant="secondary" size="sm" onClick={handleRetry} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> 刷新
          </Button>
        }
      />

      <Segmented
        options={ANDROID_TABS.map(({ key, label, Icon }) => ({ value: key, label, icon: Icon }))}
        value={activeTab}
        onChange={setTabParam}
      />

      {activeTab === 'overview' && (
        <Card padded={false}>
          <RecordTableSection
            loading={showLoading}
            error={showError}
            rows={[]}
            totalCount={overviewEntries.length}
            onClearFilter={() => undefined}
            onExport={() => exportKvCsv(overviewEntries, 'overview')}
            onRetry={handleRetry}
            emptyTitle={EMPTY_COPY.overview.title}
            emptyDescription={EMPTY_COPY.overview.description}
          >
            <div className="p-5">
              <KeyValueGrid
                entries={overviewEntries}
                labels={ANDROID_FIELD_LABELS}
                onSelect={(key, value) => setDetailRow({ key, value })}
              />
            </div>
          </RecordTableSection>
        </Card>
      )}

      {activeTab === 'apps' && (
        <AppsTab
          apps={apps}
          loading={showLoading}
          error={showError}
          taskId={taskId}
          onRetry={handleRetry}
        />
      )}

      {activeTab === 'db' && (
        <DbTab
          databases={databases}
          loading={showLoading}
          error={showError}
          taskId={taskId}
          onRetry={handleRetry}
        />
      )}

      {(activeTab === 'qqnt' || activeTab === 'wechat') && (
        <CommTab
          kind={activeTab}
          label={activeTab === 'qqnt' ? 'QQ/NT' : '微信'}
          bundle={(activeBundle as CommBundle | undefined) ?? null}
          taskId={taskId}
          loading={showLoading}
          error={showError}
          onRetry={handleRetry}
        />
      )}

      {activeTab === 'llm' && (
        <Card padded={false}>
          <RecordTableSection
            loading={showLoading}
            error={showError}
            rows={[]}
            totalCount={llmEntries.length}
            onClearFilter={() => undefined}
            onExport={() => exportKvCsv(llmEntries, 'llm')}
            onRetry={handleRetry}
            emptyTitle={EMPTY_COPY.llm.title}
            emptyDescription={EMPTY_COPY.llm.description}
          >
            <div className="p-5 space-y-4">
              {llmEntries.map(([key, value]) => (
                <div key={key}>
                  <p className="section-label mb-1.5">{ANDROID_FIELD_LABELS[key] ?? key}</p>
                  <p className="text-sm text-ink-700 dark:text-ink-300 leading-relaxed whitespace-pre-wrap break-all">
                    {cellText(value)}
                  </p>
                </div>
              ))}
            </div>
          </RecordTableSection>
        </Card>
      )}

      <RecordDetailDrawer
        row={detailRow}
        onClose={() => setDetailRow(null)}
        title={
          detailRow
            ? `${ANDROID_FIELD_LABELS[String(detailRow.key)] ?? String(detailRow.key)} 字段值`
            : ''
        }
        description={detailRow ? '概览字段详情' : undefined}
        fieldLabels={ANDROID_FIELD_LABELS}
      />
    </div>
  );
}
