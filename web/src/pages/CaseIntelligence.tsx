import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import IntelligenceReportReader from '../components/case-intel/IntelligenceReportReader';
import ForensicReportPage from './ForensicReportPage';
import Card from '../components/ui/Card';
import EmptyState from '../components/ui/EmptyState';
import { cx } from '../lib/utils';
import { FileText } from 'lucide-react';
import { PageHeader } from '../components/ui/PageScaffold';
import { useUrlState } from '../hooks/useUrlState';

/**
 * 证据研判 — report reader page. Two views:
 *  - 取证报告 (R2 forensic snapshot / narrative) — the current default
 *  - 历史研判报告 (legacy Chain B) — only via explicit ?tab=intelligence
 */
export default function CaseIntelligence() {
  const [searchParams] = useSearchParams();
  const caseId = searchParams.get('case_id');
  const urlTaskId = searchParams.get('task_id') || searchParams.get('taskId');
  const activeContextId = caseId || urlTaskId;

  // Tab mirrors the URL so views survive reloads and stay shareable.
  const [reportTab, setReportTab] = useUrlState('tab', 'forensic');

  const forensicScopeType = caseId ? ('case' as const) : ('task' as const);
  const forensicScopeId = caseId || urlTaskId;

  const placeholder = useMemo(() => {
    if (activeContextId) return null;
    return (
      <Card>
        <EmptyState title="选择一个任务进入证据研判" description="请在顶部任务选择器中选择一个镜像任务。" />
      </Card>
    );
  }, [activeContextId]);

  if (!activeContextId) return placeholder;

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader icon={ FileText } tone="amber" title="证据研判" subtitle="智能研判结论与证据清单" />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
          {(
            [
              { key: 'forensic', label: '取证报告' },
              { key: 'intelligence', label: '历史研判报告' },
            ] as const
          ).map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setReportTab(key)}
              className={cx(
                'px-3.5 py-1.5 text-xs font-medium transition-colors',
                reportTab === key
                  ? 'bg-accent-600 text-white'
                  : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {urlTaskId && (
          <Link
            to={`/investigation?task_id=${encodeURIComponent(urlTaskId)}`}
            className="ml-auto btn-ghost btn-sm"
          >
            <ArrowLeft size={13} />
            返回调查工作台
          </Link>
        )}
      </div>

      {reportTab === 'intelligence' ? (
        <IntelligenceReportReader taskId={activeContextId} />
      ) : (
        <ForensicReportPage
          key={`${forensicScopeType}-${forensicScopeId}`}
          scopeType={forensicScopeType}
          scopeId={forensicScopeId!}
        />
      )}
    </div>
  );
}
