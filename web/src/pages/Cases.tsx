import { useCallback, useEffect, useState } from 'react';
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
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useToast } from '../components/ui/Toast';
import CreateCaseModal from '../components/tasks/CreateCaseModal';
import AddTasksToCaseModal from '../components/tasks/AddTasksToCaseModal';
import ComposeCaseModal from '../components/tasks/ComposeCaseModal';
import CaseCard, { CaseCreateButton, type CasePollingState } from '../components/tasks/CaseCard';
import { Briefcase } from 'lucide-react';
import { errorMessage } from '../lib/utils';

export default function Cases() {
  const dispatch = useAppDispatch();
  const { cases, status } = useAppSelector((state) => state.cases);
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const [showCreate, setShowCreate] = useState(false);
  const [showCompose, setShowCompose] = useState(false);
  const [addTasksToCaseId, setAddTasksToCaseId] = useState<string | null>(null);
  const [polling, setPolling] = useState<Record<string, CasePollingState>>({});
  const [deleteTarget, setDeleteTarget] = useState<ForensicCase | null>(null);

  useEffect(() => {
    void dispatch(fetchCases());
    void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
  }, [dispatch]);

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

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ink-900 dark:text-ink-100">案件管理</h1>
          <p className="text-xs text-ink-500 dark:text-ink-400 mt-0.5">
            多镜像案件：跨镜像关联分析与统一报告
          </p>
        </div>
        <CaseCreateButton onClick={() => setShowCreate(true)} onCompose={() => setShowCompose(true)} />
      </div>

      {status === 'loading' && cases.length === 0 ? (
        <LoadingBlock text="正在加载案件…" />
      ) : cases.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<Briefcase size={36} />}
            title="暂无案件"
            description="创建案件可将多个镜像任务组织在一起，并进行跨镜像关联分析。"
            action={<CaseCreateButton onClick={() => setShowCreate(true)} onCompose={() => setShowCompose(true)} />}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {cases.map((c) => (
            <CaseCard
              key={c.id}
              forensicCase={c}
              tasks={tasks}
              polling={polling[c.id]}
              onStartAnalysis={handleStartAnalysis}
              onAddTasks={setAddTasksToCaseId}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
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
