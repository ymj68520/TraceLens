// EvidenceListPanel.jsx
// Workbench 左栏：Evidence Workspace 列表（任务全量 evidence，或选中 Event 的
// authoritative evidence 关联）。纯展示组件，selection 语义由页面持有。
import { CircleAlert, RefreshCw, FileSearch } from 'lucide-react';
import Badge from '../../common/Badge';
import Spinner from '../../common/Spinner';
import { useTranslation } from '../../../hooks/useTranslation';

// item: { key, sublabel, badgeText, badgeVariant }
const EvidenceListPanel = ({
    title,
    items,
    selectedKey,
    onSelect,
    loading = false,
    error = null,
    onRetry,
    emptyText,
}) => {
    const { t } = useTranslation();

    return (
        <div className="flex flex-col h-full" data-testid="evidence-workspace">
            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-white/10 dark:border-slate-700/40">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {title}
                </h2>
                {onRetry && (
                    <button
                        type="button"
                        onClick={onRetry}
                        disabled={loading}
                        className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 disabled:opacity-50"
                        title={t('investigation_workbench.refresh')}
                    >
                        <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                    </button>
                )}
            </div>

            <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
                {error ? (
                    <div className="flex flex-col items-center gap-2 py-8 text-center px-3">
                        <CircleAlert size={18} className="text-rose-500" />
                        <p className="text-xs text-rose-600 dark:text-rose-400">
                            {t('investigation_workbench.load_failed')}
                            {error?.status ? ` (HTTP ${error.status})` : ''}
                        </p>
                        <button type="button" onClick={onRetry}
                            className="px-2.5 py-1 text-xs rounded-lg bg-rose-500/10 text-rose-700 dark:text-rose-300 hover:bg-rose-500/20">
                            {t('investigation_workbench.retry')}
                        </button>
                    </div>
                ) : loading && (!items || items.length === 0) ? (
                    <div className="flex items-center justify-center py-10">
                        <Spinner size="md" />
                    </div>
                ) : !items || items.length === 0 ? (
                    <div className="flex flex-col items-center gap-1.5 py-10 text-slate-400 dark:text-slate-500">
                        <FileSearch size={18} />
                        <p className="text-xs">{emptyText || t('investigation_workbench.no_evidence')}</p>
                    </div>
                ) : (
                    items.map((item) => {
                        const isSelected = item.key === selectedKey;
                        return (
                            <button
                                key={item.key}
                                type="button"
                                onClick={() => onSelect(item.key)}
                                data-testid={`evidence-item-${item.key}`}
                                className={`w-full text-left px-2.5 py-2 rounded-xl transition-colors ${
                                    isSelected
                                        ? 'bg-lime-500/15 ring-1 ring-lime-500/40'
                                        : 'hover:bg-slate-100/60 dark:hover:bg-slate-800/60'
                                }`}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-xs font-mono break-all text-slate-700 dark:text-slate-200">
                                        {item.key}
                                    </span>
                                    {item.badgeText && (
                                        <Badge variant={item.badgeVariant || 'gray'} size="sm" className="shrink-0">
                                            {item.badgeText}
                                        </Badge>
                                    )}
                                </div>
                                {item.sublabel && (
                                    <span className="block mt-0.5 text-[10px] text-slate-400 dark:text-slate-500 break-all">
                                        {item.sublabel}
                                    </span>
                                )}
                            </button>
                        );
                    })
                )}
            </div>
        </div>
    );
};

export default EvidenceListPanel;
