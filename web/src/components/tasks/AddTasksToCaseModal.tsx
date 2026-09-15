import { useMemo, useState } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { associateTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import FormField from '../ui/FormField';
import TaskCheckList from '../cases/TaskCheckList';
import { errorMessage } from '../../lib/utils';
import { required, custom, validateForm, isValid, type FieldRules } from '../../lib/validation';

interface AddTasksToCaseModalProps {
  /** Set when the user picked a case first and is choosing tasks for it. */
  fixedCaseId?: string;
  /** Set when the user picked a task first and is choosing a target case. */
  fixedTaskId?: string;
  onClose: () => void;
}

/** Fields validated before submission; taskCount mirrors the selection size. */
type AddValues = { caseId: string; taskCount: number };

const ADD_RULES: FieldRules<AddValues> = {
  caseId: [required('请选择目标案件')],
  taskCount: [custom((v) => ((v as number) > 0 ? null : '请至少选择一个任务'))],
};

/**
 * Associate already-completed tasks to a case. The backend pre-populates the
 * reuse state so the next cross-image run skips re-analysis.
 */
export default function AddTasksToCaseModal({ fixedCaseId, fixedTaskId, onClose }: AddTasksToCaseModalProps) {
  const dispatch = useAppDispatch();
  const { cases } = useAppSelector((state) => state.cases);
  const { tasks, status: tasksStatus } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const [selectedCaseId, setSelectedCaseId] = useState(fixedCaseId || '');
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(
    fixedTaskId ? new Set([fixedTaskId]) : new Set(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof AddValues, string>>>({});

  const candidateTasks = useMemo(() => {
    const completed = (tasks || []).filter(
      (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
    );
    if (!selectedCaseId) return completed;
    const target = cases.find((c) => c.id === selectedCaseId);
    const existing = new Set(target?.task_ids || []);
    return completed.filter((t) => !existing.has(t.id));
  }, [tasks, selectedCaseId, cases]);

  const toggleTask = (taskId: string) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const tasksLoading = tasksStatus === 'loading' && tasks.length === 0;

  const handleSubmit = async () => {
    const nextErrors = validateForm(ADD_RULES, {
      caseId: selectedCaseId,
      taskCount: selectedTaskIds.size,
    });
    setErrors(nextErrors);
    if (!isValid(nextErrors)) return;
    setSubmitting(true);
    try {
      const result = (await dispatch(
        associateTasks({ caseId: selectedCaseId, taskIds: [...selectedTaskIds] }),
      ).unwrap()) as { reused?: unknown[] };
      const reused = result?.reused?.length ?? 0;
      toast.success(`已关联 ${selectedTaskIds.size} 个任务（复用分析 ${reused} 个）`);
      void dispatch(fetchCases());
      void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
      onClose();
    } catch (err) {
      toast.error(`关联失败：${errorMessage(err)}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="关联任务到案件" width="lg">
      <div className="space-y-4">
        {!fixedCaseId && (
          <FormField
            label="目标案件"
            htmlFor="add-tasks-case"
            required
            error={errors.caseId}
            hint="任务将关联到所选案件，供跨镜像分析复用"
          >
            <select
              id="add-tasks-case"
              className="select"
              value={selectedCaseId}
              onChange={(e) => setSelectedCaseId(e.target.value)}
            >
              <option value="">选择案件…</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}（{c.task_ids?.length ?? 0} 个任务）
                </option>
              ))}
            </select>
          </FormField>
        )}

        <FormField
          label="选择已完成任务"
          hint={`已选 ${selectedTaskIds.size} 个，仅列出未加入该案件的任务`}
          error={errors.taskCount}
        >
          <TaskCheckList
            tasks={candidateTasks}
            selected={selectedTaskIds}
            onToggle={toggleTask}
            loading={tasksLoading}
            maxHeightClass="max-h-64"
            emptyTitle="没有可关联的已完成任务"
            emptyDescription="仅已完成且生成文件库、尚未加入该案件的任务可以关联。"
          />
        </FormField>

        <p className="text-2xs text-ink-500 dark:text-ink-400 leading-relaxed">
          注意：任务的既有文件描述是在其原始案情上下文中生成的，跨镜像分析将原样复用。
        </p>

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={submitting}>取消</Button>
          <Button variant="primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '关联中…' : `关联 ${selectedTaskIds.size} 个任务`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
