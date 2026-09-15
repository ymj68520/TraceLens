import { useMemo, useState, type FormEvent } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { createCaseWithTasks, fetchCases } from '../../store/caseSlice';
import { fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import FormField from '../ui/FormField';
import TaskCheckList from '../cases/TaskCheckList';
import { errorMessage } from '../../lib/utils';
import {
  required,
  minLength,
  maxLength,
  custom,
  validateForm,
  isValid,
  type FieldRules,
} from '../../lib/validation';

interface ComposeCaseModalProps {
  preselectedTaskIds?: string[];
  onClose: () => void;
}

/** Fields validated before submission; taskCount mirrors the selection size. */
type ComposeValues = { name: string; description: string; taskCount: number };

const COMPOSE_RULES: FieldRules<ComposeValues> = {
  name: [
    required('请输入案件名称'),
    minLength(2, '案件名称至少 2 个字符'),
    maxLength(60, '案件名称最多 60 个字符'),
  ],
  description: [maxLength(500, '案情描述最多 500 个字符')],
  taskCount: [custom((v) => ((v as number) > 0 ? null : '请至少选择一个已完成的镜像任务'))],
};

/**
 * Compose a case from one or more already-analyzed tasks. No new scans are
 * launched; the thunk creates the case with imagePaths=[] and associates the
 * selected tasks, so existing analysis is reused as-is.
 */
export default function ComposeCaseModal({ preselectedTaskIds = [], onClose }: ComposeCaseModalProps) {
  const dispatch = useAppDispatch();
  const { tasks, status: tasksStatus } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set(preselectedTaskIds));
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof ComposeValues, string>>>({});

  const candidateTasks = useMemo(
    () =>
      (tasks || []).filter(
        (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
      ),
    [tasks],
  );

  const toggleTask = (taskId: string) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const selectAll = () => setSelectedTaskIds(new Set(candidateTasks.map((t) => t.id)));
  const clearAll = () => setSelectedTaskIds(new Set());

  const tasksLoading = tasksStatus === 'loading' && tasks.length === 0;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const nextErrors = validateForm(COMPOSE_RULES, {
      name,
      description,
      taskCount: selectedTaskIds.size,
    });
    setErrors(nextErrors);
    if (!isValid(nextErrors)) return;
    setSubmitting(true);
    try {
      await dispatch(
        createCaseWithTasks({
          name: name.trim(),
          description: description.trim(),
          imagePaths: [],
          associateTaskIds: [...selectedTaskIds],
        }),
      ).unwrap();
      toast.success(`案件「${name.trim()}」已创建，复用 ${selectedTaskIds.size} 个镜像的既有分析`);
      void dispatch(fetchCases());
      void dispatch(fetchTasks({ status: 'all', priority: 'all' }));
      onClose();
    } catch (err) {
      toast.error(`组案失败：${errorMessage(err)}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="从已有任务组建案件" width="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField
          label="案件名称"
          htmlFor="compose-name"
          required
          error={errors.name}
          hint="2–60 个字符"
        >
          <input
            id="compose-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
            placeholder="例如：XX 专案"
            autoComplete="off"
          />
        </FormField>

        <FormField
          label="案情描述"
          htmlFor="compose-desc"
          error={errors.description}
          hint="可选，将作为跨镜像关联分析的上下文"
        >
          <textarea
            id="compose-desc"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="input resize-y"
            placeholder="案件背景说明…"
          />
        </FormField>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="field-label mb-0">选择镜像任务（{selectedTaskIds.size} 已选）</span>
            <span className="space-x-2 text-2xs">
              <button
                type="button"
                className="text-accent-600 dark:text-accent-400 hover:underline"
                onClick={selectAll}
              >
                全选
              </button>
              <button type="button" className="text-ink-500 hover:underline" onClick={clearAll}>
                清空
              </button>
            </span>
          </div>
          <TaskCheckList
            tasks={candidateTasks}
            selected={selectedTaskIds}
            onToggle={toggleTask}
            loading={tasksLoading}
            maxHeightClass="max-h-56"
            emptyTitle="没有已完成且含文件库的任务"
            emptyDescription="仅已完成并生成 files.db 的任务可以组建案件。"
          />
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={submitting}>取消</Button>
          <Button variant="primary" type="submit" disabled={submitting}>
            {submitting ? '创建中…' : '创建案件'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
