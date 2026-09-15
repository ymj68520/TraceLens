import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Briefcase, RotateCw, Search, X } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import {
  fetchCases,
  createCaseWithTasks,
  startCrossAnalysis,
  updateCaseStatus,
  deleteCase,
  deleteCaseWithTasks,
  type CreateCaseWithTasksArgs,
} from '../store/caseSlice';
import { fetchTasks, fetchTasksSilent } from '../store/taskSlice';
import { pollMultiAnalysis } from '../services/caseGroupService';
import type { ForensicCase } from '../types/api';
import EmptyState from '../components/ui/EmptyState';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import Button from '../components/ui/Button';
import { useToast } from '../components/ui/Toast';
import { PageHeader, StatStrip, type StatItem } from '../components/ui/PageScaffold';
import { useDebouncedValue, useUrlState } from '../hooks/useUrlState';
import { errorMessage } from '../lib/utils';
import CreateCaseModal from '../components/tasks/CreateCaseModal';
import AddTasksToCaseModal from '../components/tasks/AddTasksToCaseModal';
import ComposeCaseModal from '../components/tasks/ComposeCaseModal';
import CaseCard, { CaseCreateButton, type CasePollingState } from '../components/tasks/CaseCard';
import CaseDetail from '../components/cases/CaseDetail';
import CaseCardSkeleton from '../components/cases/CaseCardSkeleton';

/** Cases shown when the「任务数 Top」chip is active. */
const TOP_N = 5;

type CaseFilter = 'all' | 'top' | `status:${string}`;

export default function Cases() {
  const dispatch = useAppDispatch();
  const { cases, status, error } = useAppSelector((state) => state.cases);
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  // Detail view persists in the URL (?case=<id>) so reloads/share keep context.
  const [selectedCaseId, setSelectedCaseId] = useUrlState('case', '');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [filter, setFilter] = useState<CaseFilter>('all');

  const [showCreate, setShowCreate] = useState(false);
  const [showCompose, setShowCompose] = useState(false);
  const [addTasksToCaseId, setAddTasksToCaseId] = useState<string | null>(null);
  const [polling, setPolling] = useState<Record<string, CasePollingState>>({});
  const [deleteTarget, setDeleteTarget] = useState<ForensicCase | null>(null);

  useEffect(() => {
    void dispatch(fetchCases());
    void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
  }, [dispatch]);

  // Failure toast: fire once per failed load cycle; the retry button re-dispatches.
  const errorToasted = useRef(false);
  useEffect(() => {
    if (status === 'failed') {
      if (!errorToasted.current) {
        errorToasted.current = true;
        toast.error(`案件列表加载失败：${errorMessage(error)}`);
      }
    } else {
      errorToasted.current = false;
    }
  }, [status, error, toast]);

  const handleRetry = useCallback(() => {
    void dispatch(fetchCases());
  }, [dispatch]);

  const selectedCase = useMemo(
    () => (selectedCaseId ? cases.find((c) => c.id === selectedCaseId) ?? null : null),
    [cases, selectedCaseId],
  );

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of cases) {
      const key = c.status ?? 'open';
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [cases]);

  const filteredCases = useMemo(() => {
    let list = cases;
    if (filter === 'top') {
      list = [...list]
        .sort((a, b) => (b.task_ids?.length ?? 0) - (a.task_ids?.length ?? 0))
        .slice(0, TOP_N);
    } else if (filter.startsWith('status:')) {
      const s = filter.slice('status:'.length);
      list = list.filter((c) => (c.status ?? 'open') === s);
    }
    const q = debouncedSearch.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (c) => c.name.toLowerCase().includes(q) || (c.description ?? '').toLowerCase().includes(q),
      );
    }
    return list;
  }, [cases, filter, debouncedSearch]);

  const stats: StatItem[] = [
    { label: '全部案件', value: cases.length, active: filter === 'all', onClick: () => setFilter('all') },
    {
      label: '待分析',
      value: statusCounts['open'] ?? 0,
      dotClass: 'bg-sky-500',
      active: filter === 'status:open',
      onClick: () => setFilter('status:open'),
    },
    {
      label: '分析中',
      value: statusCounts['analysing'] ?? 0,
      dotClass: 'bg-amber-400',
      active: filter === 'status:analysing',
      onClick: () => setFilter('status:analysing'),
    },
    {
      label: '已完成',
      value: statusCounts['completed'] ?? 0,
      dotClass: 'bg-emerald-500',
      active: filter === 'status:completed',
      onClick: () => setFilter('status:completed'),
    },
    {
      label: '失败',
      value: statusCounts['failed'] ?? 0,
      dotClass: 'bg-rose-500',
      active: filter === 'status:failed',
      onClick: () => setFilter('status:failed'),
    },
    {
      label: '任务数 Top',
      value: Math.min(TOP_N, cases.length),
      dotClass: 'bg-accent-500',
      active: filter === 'top',
      onClick: () => setFilter('top'),
    },
  ];

  const handleCreate = useCallback(
    async (formData: CreateCaseWithTasksArgs) => {
      try {
        await dispatch(createCaseWithTasks(formData)).unwrap();
        setShowCreate(false);
        toast.success('案件创建成功，任务已启动');
        void dispatch(fetchCases());
      } catch (err) {
        toast.error(`创建失败：${errorMessage(err)}`);
        throw err;
      }
    },
    [dispatch, toast],
  );

  const handleStartAnalysis = useCallback(
    async (forensicCase: ForensicCase) => {
      if (!forensicCase.task_ids?.length) {
        toast.error('该案件没有关联任务');
        return;
      }
      const caseTasks = forensicCase.task_ids
        .map((id) => tasks.find((t) => t.id === id))
        .filter(Boolean);
      const filesDbPaths = caseTasks
        .map((t) => (t as { output_files_db?: string })?.output_files_db)
        .filter((p): p is string => Boolean(p));

      if (filesDbPaths.length !== forensicCase.task_ids.length) {
        const missing = forensicCase.task_ids.length - filesDbPaths.length;
        toast.error(`有 ${missing} 个任务尚未生成 files.db，请等待分析完成`);
        return;
      }

      try {
        const result = await dispatch(
          startCrossAnalysis({
            caseId: forensicCase.id,
            taskIds: forensicCase.task_ids,
            filesDbPaths,
            caseDescription: forensicCase.description,
          }),
        ).unwrap();

        toast.success('跨镜像分析已启动');
        const jobId = result.job_id as string;
        setPolling((p) => ({
          ...p,
          [forensicCase.id]: { jobId, stage: '初始化', message: '正在启动跨镜像分析…' },
        }));

        pollMultiAnalysis(
          jobId,
          (s) => {
            const prog = (s.progress || {}) as { stage?: string; message?: string };
            setPolling((p) => ({
              ...p,
              [forensicCase.id]: {
                jobId,
                stage: prog.stage || (s.status === 'completed' ? '完成' : '分析中'),
                message: prog.message || '',
              },
            }));
            if (s.status === 'completed') {
              dispatch(updateCaseStatus({ caseId: forensicCase.id, status: 'completed' }));
              setPolling((p) => {
                const next = { ...p };
                delete next[forensicCase.id];
                return next;
              });
              toast.success('跨镜像分析完成');
              void dispatch(fetchCases());
              void dispatch(fetchTasksSilent({ status: 'all', priority: 'all' }));
            }
          },
          5000,
        ).catch((e: Error) => {
          setPolling((p) => {
            const next = { ...p };
            delete next[forensicCase.id];
            return next;
          });
          toast.error(`跨镜像分析失败：${e.message}`);
          void dispatch(fetchCases());
        });
      } catch (err) {
        toast.error(`启动失败：${errorMessage(err)}`);
      }
    },
    [dispatch, tasks, toast],
  );

  const handleDelete = async (withTasks: boolean) => {
    if (!deleteTarget) return;
    try {
      if (withTasks) {
        await dispatch(
          deleteCaseWithTasks({ caseId: deleteTarget.id, taskIds: deleteTarget.task_ids || [] }),
        ).unwrap();
        toast.success('案件及其任务已删除');
      } else {
        await dispatch(deleteCase(deleteTarget.id)).unwrap();
        toast.success('案件已删除（任务保留）');
      }
    } catch (err) {
      toast.error(`删除失败：${errorMessage(err)}`);
    } finally {
      setDeleteTarget(null);
    }
  };

  const isInitialLoading = status === 'loading' && cases.length === 0;
  const isLoadFailed = status === 'failed' && cases.length === 0;

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader
        icon={Briefcase}
        tone="accent"
        title="案件管理"
        subtitle={
          selectedCase
            ? `案件详情 · ${selectedCase.name}`
            : '将任务证据组织为可复查的案件，支持跨镜像关联分析'
        }
        actions={
          selectedCase ? undefined : (
            <CaseCreateButton onClick={() => setShowCreate(true)} onCompose={() => setShowCompose(true)} />
          )
        }
      />

      {selectedCase ? (
        <CaseDetail
          forensicCase={selectedCase}
          tasks={tasks}
          polling={polling[selectedCase.id]}
          onBack={() => setSelectedCaseId('')}
          onStartAnalysis={handleStartAnalysis}
          onAddTasks={setAddTasksToCaseId}
          onDelete={setDeleteTarget}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <StatStrip className="flex-1 min-w-0" stats={stats} />
            <div className="relative w-full sm:w-64">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none"
                aria-hidden
              />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="input pl-8 pr-8 py-1.5 text-xs"
                placeholder="搜索案件名称或描述…"
                aria-label="搜索案件"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 transition-colors"
                  aria-label="清除搜索"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          </div>

          {isInitialLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              <CaseCardSkeleton count={6} />
            </div>
          ) : isLoadFailed ? (
            <div className="card">
              <EmptyState
                icon={<RotateCw size={32} />}
                title="案件列表加载失败"
                description="网络或分析服务暂时不可用，请稍后重试。"
                action={
                  <Button variant="primary" size="sm" onClick={handleRetry}>
                    <RotateCw size={14} /> 重试
                  </Button>
                }
              />
            </div>
          ) : cases.length === 0 ? (
            <div className="card">
              <EmptyState
                icon={<Briefcase size={36} />}
                title="暂无案件"
                description="创建案件可将多个镜像任务组织在一起，并进行跨镜像关联分析。"
                action={
                  <CaseCreateButton onClick={() => setShowCreate(true)} onCompose={() => setShowCompose(true)} />
                }
              />
            </div>
          ) : filteredCases.length === 0 ? (
            <div className="card">
              <EmptyState
                icon={<Search size={32} />}
                title="没有匹配的案件"
                description="没有符合当前搜索关键词或筛选条件的案件，试试其他关键词或清除筛选。"
                action={
                  <Button
                    size="sm"
                    onClick={() => {
                      setSearch('');
                      setFilter('all');
                    }}
                  >
                    清除搜索与筛选
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {filteredCases.map((c) => (
                <CaseCard
                  key={c.id}
                  forensicCase={c}
                  tasks={tasks}
                  polling={polling[c.id]}
                  onOpenDetail={(fc) => setSelectedCaseId(fc.id)}
                  onStartAnalysis={handleStartAnalysis}
                  onAddTasks={setAddTasksToCaseId}
                  onDelete={setDeleteTarget}
                />
              ))}
            </div>
          )}
        </>
      )}

      {showCreate && (
        <CreateCaseModal
          onSubmit={handleCreate}
          onClose={() => setShowCreate(false)}
          existingTasks={tasks}
        />
      )}

      {showCompose && <ComposeCaseModal onClose={() => setShowCompose(false)} />}

      {addTasksToCaseId && (
        <AddTasksToCaseModal fixedCaseId={addTasksToCaseId} onClose={() => setAddTasksToCaseId(null)} />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除案件"
        message={`删除案件「${deleteTarget?.name}」？可选择同时删除其关联任务（不可恢复）。`}
        danger
        confirmText="仅删案件"
        cancelText="取消"
        onConfirm={() => handleDelete(false)}
        onCancel={() => setDeleteTarget(null)}
      />
      {deleteTarget && (deleteTarget.task_ids?.length ?? 0) > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
          <button
            type="button"
            className="btn-danger shadow-pop"
            onClick={() => handleDelete(true)}
          >
            同时删除 {deleteTarget.task_ids?.length} 个任务
          </button>
        </div>
      )}
    </div>
  );
}
