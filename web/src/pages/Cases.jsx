/**
 * Cases — Multi-image case management page.
 *
 * Features:
 *  - List all ForensicCases
 *  - Create a new case with multiple image paths (one task per image)
 *  - Show per-case task progress
 *  - "Start Cross-Image Analysis" button when all tasks completed
 *  - Show cross-image analysis job status
 *  - Delete a case (optionally with associated tasks)
 */
import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { motion } from 'framer-motion';
import { fetchCases, createCaseWithTasks, startCrossAnalysis, updateCaseStatus, deleteCase, deleteCaseWithTasks } from '../store/caseSlice';
import { fetchTasks } from '../store/taskSlice';
import { pollMultiAnalysis } from '../services/caseGroupService';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/ToastContext';
import CreateCaseModal from '../components/tasks/CreateCaseModal';

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
  const [pollingJobId, setPollingJobId] = useState(null);

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
    // Collect files_db_paths from each task (read from task details)
    // For simplicity, user must ensure tasks are completed and db paths available
    if (!forensicCase.task_ids?.length) {
      toast.error('该案件没有关联任务');
      return;
    }
    try {
      const result = await dispatch(startCrossAnalysis({
        caseId:          forensicCase.id,
        taskIds:         forensicCase.task_ids,
        filesDbPaths:    forensicCase.task_ids.map((id) => `data/tasks/${id}/files.db`),
        caseDescription: forensicCase.description,
      })).unwrap();

      toast.success('跨镜像分析已启动！');
      setPollingJobId(result.job_id);

      pollMultiAnalysis(
        result.job_id,
        (s) => {
          if (s.status === 'completed') {
            dispatch(updateCaseStatus({ caseId: forensicCase.id, status: 'completed' }));
            toast.success('跨镜像分析完成！');
            setPollingJobId(null);
          }
        },
        5000
      ).catch((e) => toast.error('跨镜像分析失败：' + e.message));
    } catch (err) {
      toast.error('启动失败：' + (err?.message || err));
    }
  }, [dispatch, toast]);

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
        <Button onClick={() => setShowCreate(true)}>➕ 新建案件</Button>
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
              isPolling={pollingJobId != null}
              navigate={navigate}
            />
          ))}
        </div>
      )}

      {showCreate && (
        <CreateCaseModal
          onSubmit={handleCreate}
          onClose={() => setShowCreate(false)}
        />
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

function CaseCard({ forensicCase: fc, tasks, onStartAnalysis, onDelete, isPolling, navigate }) {
  const statusColor = STATUS_COLOR[fc.status] || 'gray';
  const allTasksCount = fc.task_ids?.length || 0;
  
  const caseTasks = fc.task_ids?.map(id => tasks.find(t => t.id === id)).filter(Boolean) || [];
  const allTasksCompleted = caseTasks.length === allTasksCount && caseTasks.every(t => t.status === 'completed');

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
              disabled={isPolling || !allTasksCompleted}
            >
              {isPolling ? '分析中...' : (!allTasksCompleted ? '等待子任务完成' : '🔍 启动案情研判')}
            </Button>
          )}
          {fc.status === 'analysing' && (
            <div className="flex items-center gap-2 text-yellow-600 bg-yellow-50 px-3 py-1.5 rounded-lg border border-yellow-200">
              <Spinner size="sm" />
              <span className="text-sm font-medium">✨ 正在聚合案件线索...</span>
            </div>
          )}
          {fc.status === 'completed' && (
            <Button
                variant="primary"
                size="sm"
                onClick={() => navigate(`/case-report?case_id=${fc.id}`)}
                className="shadow-sm"
            >
                👀 查看完整研判报告
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
                <div className="flex items-center gap-3">
                  <span className="font-mono text-slate-400">ID:{t.id.substring(0, 6)}</span>
                  <span className="font-medium text-slate-700 dark:text-slate-300 max-w-[200px] truncate" title={t.image_path}>
                    {t.image_path.split('/').pop()}
                  </span>
                </div>
                <div className="flex items-center gap-3 w-48">
                  <div className="flex-1 w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                    <div 
                      className={`h-full ${t.status === 'completed' ? 'bg-green-500' : 'bg-purple-500'}`} 
                      style={{ width: `${t.progress_percentage || 0}%` }} 
                    />
                  </div>
                  <span className={`w-16 text-right font-medium ${t.status === 'completed' ? 'text-green-600' : 'text-purple-600'}`}>
                    {t.status === 'completed' ? '已完成' : `${t.progress_percentage || 0}%`}
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
