/**
 * Cases — Multi-image case management page.
 *
 * Features:
 *  - List all ForensicCases
 *  - Create a new case with multiple image paths (one task per image)
 *  - Show per-case task progress
 *  - "Start Cross-Image Analysis" button when all tasks completed
 *  - Show cross-image analysis job status (live stage/message from backend)
 *  - Delete a case (optionally with associated tasks)
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { motion } from 'framer-motion';
import { fetchCases, createCaseWithTasks, startCrossAnalysis, updateCaseStatus, deleteCase, deleteCaseWithTasks } from '../store/caseSlice';
import { fetchTasks, fetchTasksSilent } from '../store/taskSlice';
import { pollMultiAnalysis } from '../services/caseGroupService';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/ToastContext';
import CreateCaseModal from '../components/tasks/CreateCaseModal';
import AddTasksToCaseModal from '../components/tasks/AddTasksToCaseModal';
import ComposeCaseModal from '../components/tasks/ComposeCaseModal';

const STATUS_COLOR = {
  open:       'blue',
  analysing:  'yellow',
  completed:  'green',
  failed:     'red',
};

export default function Cases() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { cases, status, error } = useSelector((state) => state.cases);
  const { tasks } = useSelector((state) => state.tasks);
  const toast = useToast();

  const [showCreate, setShowCreate] = useState(false);

  // Per-case live polling state: { [caseId]: { jobId, stage, message } }
  const [polling, setPolling] = useState({});
  // Keep a ref so poll callbacks always see fresh state
  const pollingRef = useRef(polling);
  pollingRef.current = polling;

  // Add-tasks-to-case modal: null when closed, else the target case id
  const [addTasksToCaseId, setAddTasksToCaseId] = useState(null);
  // Compose-case-from-tasks modal (Cases-page quick entry)
  const [showCompose, setShowCompose] = useState(false);

  // Delete dialog state
  const [deleteState, setDeleteState] = useState({
    open: false,
    caseId: null,
    caseName: '',
    taskIds: [],
    loading: false,
  });

  useEffect(() => {
    dispatch(fetchCases());
    dispatch(fetchTasks({ status: 'all', priority: 'all' }));
  }, [dispatch]);

  const handleCreate = useCallback(async (formData) => {
    try {
      await dispatch(createCaseWithTasks(formData)).unwrap();
      setShowCreate(false);
      toast.success('案件创建成功，任务已启动！');
      dispatch(fetchCases());
    } catch (err) {
      toast.error('创建失败：' + (err?.message || err));
    }
  }, [dispatch, toast]);

  const handleStartAnalysis = useCallback(async (forensicCase) => {
    if (!forensicCase.task_ids?.length) {
      toast.error('该案件没有关联任务');
      return;
    }
    // Resolve real files_db paths from the task records (never hardcode).
    const caseTasks = forensicCase.task_ids
      .map((id) => tasks.find((t) => t.id === id))
      .filter(Boolean);
    const filesDbPaths = caseTasks
      .map((t) => t.output_files_db)
      .filter(Boolean);

    if (filesDbPaths.length !== forensicCase.task_ids.length) {
      const missing = forensicCase.task_ids.length - filesDbPaths.length;
      toast.error(`有 ${missing} 个任务尚未生成 files.db，请等待分析完成`);
      return;
    }

    try {
      const result = await dispatch(startCrossAnalysis({
        caseId:          forensicCase.id,
        taskIds:         forensicCase.task_ids,
        filesDbPaths,
        caseDescription: forensicCase.description,
      })).unwrap();

      toast.success('跨镜像分析已启动！');
      setPolling((p) => ({
        ...p,
        [forensicCase.id]: { jobId: result.job_id, stage: '初始化', message: '正在启动跨镜像分析...' },
      }));

      pollMultiAnalysis(
        result.job_id,
        (s) => {
          const prog = s.progress || {};
          // Live-update the stage/message for this case
          setPolling((p) => ({
            ...p,
            [forensicCase.id]: {
              jobId: result.job_id,
              stage: prog.stage || (s.status === 'completed' ? '完成' : '分析中'),
              message: prog.message || '',
            },
          }));
          if (s.status === 'completed') {
            dispatch(updateCaseStatus({ caseId: forensicCase.id, status: 'completed' }));
            setPolling((p) => { const n = { ...p }; delete n[forensicCase.id]; return n; });
            toast.success('跨镜像分析完成！');
            // Refresh both lists so progress bars + status stay accurate
            dispatch(fetchCases());
            dispatch(fetchTasksSilent({ status: 'all', priority: 'all' }));
          }
        },
        5000
      ).catch((e) => {
        setPolling((p) => { const n = { ...p }; delete n[forensicCase.id]; return n; });
        toast.error('跨镜像分析失败：' + e.message);
        dispatch(fetchCases());
      });
    } catch (err) {
      toast.error('启动失败：' + (err?.message || err));
    }
  }, [dispatch, tasks, toast]);

  // --- Delete case flow ---
  const handleDeleteCase = useCallback((fc) => {
    setDeleteState({
      open: true,
      caseId: fc.id,
      caseName: fc.name,
      taskIds: fc.task_ids || [],
      loading: false,
    });
  }, []);

  const doDeleteCase = useCallback(async (alsoDeleteTasks) => {
    const { caseId, taskIds } = deleteState;
    setDeleteState((s) => ({ ...s, loading: true }));
    try {
      if (alsoDeleteTasks && taskIds.length > 0) {
        const result = await dispatch(deleteCaseWithTasks({ caseId, taskIds })).unwrap();
        const deletedCount = result.deletedTaskIds?.length || 0;
        toast.success(`案件及 ${deletedCount} 个关联任务已删除`);
      } else {
        await dispatch(deleteCase(caseId)).unwrap();
        toast.success('案件已删除（关联任务已保留）');
      }
      // Refresh both lists
      dispatch(fetchCases());
      dispatch(fetchTasks({ status: 'all', priority: 'all' }));
    } catch (err) {
      toast.error('删除失败：' + (err?.message || err));
    } finally {
      setDeleteState({ open: false, caseId: null, caseName: '', taskIds: [], loading: false });
    }
  }, [deleteState, dispatch, toast]);

  if (status === 'loading' && cases.length === 0) {
    return <div className="flex items-center justify-center h-64"><Spinner size="lg" /></div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
            className="text-3xl font-bold text-slate-900 dark:text-white"
          >
            Cases
          </motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">
            多镜像联合分析案件管理
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setShowCompose(true)}>📂 从已分析镜像组建</Button>
          <Button onClick={() => setShowCreate(true)}>➕ 新建案件</Button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 rounded-xl">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      {/* Case list */}
      {cases.length === 0 ? (
        <Card>
          <p className="text-center py-12 text-slate-500 dark:text-slate-400">
            暂无案件，点击"新建案件"开始多镜像联合分析。
          </p>
        </Card>
      ) : (
        <div className="grid gap-4">
          {cases.map((fc) => (
            <CaseCard
              key={fc.id}
              forensicCase={fc}
              tasks={tasks}
              onStartAnalysis={handleStartAnalysis}
              onDelete={handleDeleteCase}
              onAddTasks={(caseId) => setAddTasksToCaseId(caseId)}
              polling={polling[fc.id]}
              navigate={navigate}
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

      {/* Add-tasks-to-case modal (case-card entry point) */}
      {addTasksToCaseId && (
        <AddTasksToCaseModal
          fixedCaseId={addTasksToCaseId}
          onClose={() => setAddTasksToCaseId(null)}
        />
      )}

      {/* Compose-case-from-tasks modal (Cases-page quick entry) */}
      {showCompose && (
        <ComposeCaseModal onClose={() => setShowCompose(false)} />
      )}

      {/* Delete case confirmation dialog */}
      <ConfirmDialog
        open={deleteState.open}
        onConfirm={doDeleteCase}
        onCancel={() => setDeleteState({ open: false, caseId: null, caseName: '', taskIds: [], loading: false })}
        title="删除案件"
        message={`确定要删除案件「${deleteState.caseName}」吗？此操作不可撤销。`}
        confirmText="确认删除"
        cancelText="取消"
        variant="danger"
        loading={deleteState.loading}
        checkboxLabel={
          deleteState.taskIds.length > 0
            ? `同时删除关联的 ${deleteState.taskIds.length} 个分析任务及其数据`
            : ''
        }
        checkboxDefaultChecked={false}
      />
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function CaseCard({ forensicCase: fc, tasks, onStartAnalysis, onDelete, onAddTasks, polling, navigate }) {
  const statusColor = STATUS_COLOR[fc.status] || 'gray';
  const allTasksCount = fc.task_ids?.length || 0;

  const caseTasks = fc.task_ids?.map(id => tasks.find(t => t.id === id)).filter(Boolean) || [];
  const allTasksCompleted = caseTasks.length === allTasksCount && caseTasks.every(t => t.status === 'completed');
  const failedTasks = caseTasks.filter(t => t.status === 'failed' || t.status === 'error');
  const isPolling = !!polling;

  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white truncate">{fc.name}</h3>
            <Badge variant={statusColor}>{fc.status}</Badge>
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2 mb-2">{fc.description}</p>
          <div className="flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span>🖼️ {allTasksCount} 个镜像</span>
            <span>· ID: {fc.id?.substring(0, 8)}</span>
            {fc.cross_analysis_job_id && (
              <span>· 分析作业: {fc.cross_analysis_job_id.substring(0, 8)}</span>
            )}
          </div>
        </div>
        <div className="flex-shrink-0 flex flex-col gap-2 items-end">
          {fc.status === 'open' && allTasksCount > 0 && (
            <Button
              size="sm"
              onClick={() => onStartAnalysis(fc)}
              disabled={isPolling || (!allTasksCompleted && failedTasks.length === 0)}
            >
              {isPolling ? '分析中...' : (
                !allTasksCompleted
                  ? (failedTasks.length > 0 ? `⚠️ 跳过 ${failedTasks.length} 失败任务启动` : '等待子任务完成')
                  : '🔍 启动案情研判'
              )}
            </Button>
          )}
          {fc.status === 'analysing' && (
            <div className="flex flex-col items-end gap-1.5 text-yellow-600 bg-yellow-50 px-3 py-1.5 rounded-lg border border-yellow-200 max-w-xs">
              <div className="flex items-center gap-2">
                <Spinner size="sm" />
                <span className="text-sm font-medium">✨ {polling?.stage || '聚合案件线索中...'}</span>
              </div>
              {polling?.message && (
                <span className="text-[11px] text-yellow-700 dark:text-yellow-300 text-right line-clamp-2">{polling.message}</span>
              )}
            </div>
          )}
          {fc.status === 'completed' && (
            <Button
                variant="primary"
                size="sm"
                onClick={() => navigate(`/reports/case/${fc.id}`)}
                className="shadow-sm"
            >
                👀 查看完整研判报告
            </Button>
          )}
          {/* Add already-analyzed tasks to this case (allowed unless analysing) */}
          {fc.status !== 'analysing' && (
            <Button size="sm" variant="outline" onClick={() => onAddTasks(fc.id)}>
              ➕ 添加任务
            </Button>
          )}

          {/* Delete button */}
          <motion.button
            onClick={() => onDelete(fc)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-all"
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            title="删除案件"
          >
            🗑️ 删除案件
          </motion.button>
        </div>
      </div>

      {/* Sub-tasks section */}
      {caseTasks.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
          <h4 className="text-xs font-bold text-slate-500 mb-3 ml-1 uppercase tracking-wider">关联镜像任务进度 ({caseTasks.length})</h4>
          <div className="space-y-2">
            {caseTasks.map(t => (
              <div key={t.id} className="flex justify-between items-center text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="font-mono text-slate-400">ID:{t.id.substring(0, 6)}</span>
                  <span className="font-medium text-slate-700 dark:text-slate-300 max-w-[200px] truncate" title={t.image_path}>
                    {t.image_path?.split('/').pop() || t.id}
                  </span>
                  {/* Quick links into task-context pages */}
                  {t.status === 'completed' && (
                    <span className="flex items-center gap-1.5 ml-1">
                      <button
                        onClick={() => navigate(`/files?task_id=${t.id}`)}
                        className="text-slate-400 hover:text-blue-600 transition-colors"
                        title="查看文件"
                      >📁</button>
                      <button
                        onClick={() => navigate(`/timeline?task_id=${t.id}`)}
                        className="text-slate-400 hover:text-purple-600 transition-colors"
                        title="查看时间线"
                      >⏱</button>
                      <button
                        onClick={() => navigate(`/reports/task/${t.id}`)}
                        className="text-slate-400 hover:text-emerald-600 transition-colors"
                        title="单镜像报告"
                      >📄</button>
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 w-48">
                  <ProgressBar status={t.status} progress={t.progress_percentage || 0} />
                  <span className="w-16 text-right font-medium">
                    {statusLabel(t)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// Progress bar whose color reflects the task status.
function ProgressBar({ status, progress }) {
  const barColor =
    status === 'completed' ? 'bg-green-500' :
    status === 'failed' || status === 'error' ? 'bg-red-500' :
    status === 'running' || status === 'pending' || status === 'queued' ? 'bg-purple-500' :
    'bg-slate-400';
  return (
    <div className="flex-1 w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
      <div className={`h-full ${barColor}`} style={{ width: `${progress}%` }} />
    </div>
  );
}

// Human-readable, status-aware progress label.
function statusLabel(t) {
  if (t.status === 'completed') return <span className="text-green-600">已完成</span>;
  if (t.status === 'failed' || t.status === 'error') return <span className="text-red-600">失败</span>;
  if (t.status === 'queued' || t.status === 'pending') return <span className="text-slate-500">排队中</span>;
  return <span className="text-purple-600">{t.progress_percentage || 0}%</span>;
}
