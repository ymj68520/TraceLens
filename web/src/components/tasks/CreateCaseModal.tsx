import { useMemo, useState, type FormEvent } from 'react';
import { Plus, X } from 'lucide-react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import FormField from '../ui/FormField';
import StepIndicator from '../cases/StepIndicator';
import TaskCheckList from '../cases/TaskCheckList';
import type { ForensicTask } from '../../types/api';
import type { CreateCaseWithTasksArgs } from '../../store/caseSlice';
import {
  required,
  minLength,
  maxLength,
  validateForm,
  isValid,
  type FieldRules,
} from '../../lib/validation';

interface CreateCaseModalProps {
  onSubmit: (data: CreateCaseWithTasksArgs) => Promise<void>;
  onClose: () => void;
  existingTasks?: ForensicTask[];
}

type FormState = {
  name: string;
  description: string;
  imagePaths: string[];
  priority: string;
  androidAnalyze: boolean;
};

/** Fields validated at wizard step 1. */
type BasicValues = Pick<FormState, 'name' | 'description'>;

const BASIC_RULES: FieldRules<BasicValues> = {
  name: [
    required('请输入案件名称'),
    minLength(2, '案件名称至少 2 个字符'),
    maxLength(60, '案件名称最多 60 个字符'),
  ],
  description: [maxLength(500, '案情描述最多 500 个字符')],
};

const INIT: FormState = {
  name: '',
  description: '',
  imagePaths: [''],
  priority: 'normal',
  androidAnalyze: false,
};

const STEPS = ['基本信息', '选择关联任务'];

/**
 * Two-step case-creation wizard:
 * 1. Basic info (name required, optional description) — validated inline.
 * 2. Task association: new image paths (one task each) and/or existing
 *    completed tasks whose analysis will be reused.
 */
export default function CreateCaseModal({ onSubmit, onClose, existingTasks = [] }: CreateCaseModalProps) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(INIT);
  const [basicErrors, setBasicErrors] = useState<Partial<Record<keyof BasicValues, string>>>({});
  const [stepError, setStepError] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [associateTaskIds, setAssociateTaskIds] = useState<Set<string>>(new Set());

  const set = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: val }));

  const setImagePath = (idx: number, val: string) =>
    setForm((f) => {
      const paths = [...f.imagePaths];
      paths[idx] = val;
      return { ...f, imagePaths: paths };
    });

  const addImage = () => setForm((f) => ({ ...f, imagePaths: [...f.imagePaths, ''] }));
  const removeImage = (idx: number) =>
    setForm((f) => ({ ...f, imagePaths: f.imagePaths.filter((_, i) => i !== idx) }));

  const associableTasks = useMemo(
    () =>
      (existingTasks || []).filter(
        (t) => t.status === 'completed' && (t as { output_files_db?: string }).output_files_db,
      ),
    [existingTasks],
  );

  const toggleAssociate = (taskId: string) =>
    setAssociateTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const validImagePaths = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const p of form.imagePaths) {
      const trimmed = (p || '').trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        out.push(trimmed);
      }
    }
    return out;
  }, [form.imagePaths]);

  const totalImages = validImagePaths.length + associateTaskIds.size;

  const validateBasics = () => {
    const errors = validateForm(BASIC_RULES, { name: form.name, description: form.description });
    setBasicErrors(errors);
    return isValid(errors);
  };

  const goNext = () => {
    setStepError('');
    if (validateBasics()) setStep(1);
  };

  const goBack = () => {
    setStepError('');
    setStep(0);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (step !== 1) {
      goNext();
      return;
    }
    setStepError('');
    if (totalImages === 0) {
      setStepError('请至少填写一个新镜像路径，或勾选一个已完成的任务');
      return;
    }
    if (!validateBasics()) {
      setStep(0);
      return;
    }
    setIsCreating(true);
    try {
      await onSubmit({
        name: form.name.trim(),
        description: form.description.trim(),
        imagePaths: validImagePaths,
        priority: form.priority,
        androidAnalyze: form.androidAnalyze,
        associateTaskIds: [...associateTaskIds],
      });
    } catch (err) {
      setStepError((err as Error)?.message || String(err));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="新建案件" width="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <StepIndicator steps={STEPS} current={step} />

        {stepError && (
          <p
            className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md"
            role="alert"
          >
            {stepError}
          </p>
        )}

        {step === 0 ? (
          <div className="space-y-4">
            <FormField
              label="案件名称"
              htmlFor="case-name"
              required
              error={basicErrors.name}
              hint="2–60 个字符，用于案件列表与报告展示"
            >
              <input
                id="case-name"
                type="text"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                className="input"
                placeholder="例如：XX 专案"
                autoComplete="off"
              />
            </FormField>

            <FormField
              label="案情描述"
              htmlFor="case-desc"
              error={basicErrors.description}
              hint="可选，将作为跨镜像关联分析的上下文"
            >
              <textarea
                id="case-desc"
                rows={3}
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                className="input resize-y"
                placeholder="案件背景说明…"
              />
            </FormField>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="field-label mb-0">新镜像路径（每个镜像创建一个任务）</span>
                <button
                  type="button"
                  onClick={addImage}
                  className="text-2xs text-accent-600 dark:text-accent-400 hover:underline inline-flex items-center gap-0.5"
                >
                  <Plus size={12} /> 添加镜像
                </button>
              </div>
              <div className="space-y-2">
                {form.imagePaths.map((path, idx) => (
                  <div key={idx} className="flex gap-2">
                    <input
                      type="text"
                      value={path}
                      onChange={(e) => setImagePath(idx, e.target.value)}
                      className="input font-mono text-xs flex-1"
                      placeholder="/path/to/image.dd"
                    />
                    {form.imagePaths.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeImage(idx)}
                        className="p-2 text-ink-400 hover:text-rose-500 transition-colors"
                        aria-label="移除该镜像"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <FormField
              label="关联已完成任务"
              hint={`复用既有分析，已选 ${associateTaskIds.size} 个`}
            >
              <TaskCheckList
                tasks={associableTasks}
                selected={associateTaskIds}
                onToggle={toggleAssociate}
                maxHeightClass="max-h-40"
                showStatusBadge={false}
                emptyTitle="暂无可关联的已完成任务"
                emptyDescription="已完成且生成文件库的任务会出现在这里。"
              />
            </FormField>

            <div className="grid grid-cols-2 gap-3">
              <FormField label="任务优先级" htmlFor="case-priority">
                <select
                  id="case-priority"
                  value={form.priority}
                  onChange={(e) => set('priority', e.target.value)}
                  className="select"
                >
                  <option value="low">低</option>
                  <option value="normal">普通</option>
                  <option value="high">高</option>
                  <option value="critical">紧急</option>
                </select>
              </FormField>
              <label className="flex items-center gap-2 pt-6 text-sm text-ink-700 dark:text-ink-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  checked={form.androidAnalyze}
                  onChange={(e) => set('androidAnalyze', e.target.checked)}
                />
                执行安卓专项分析
              </label>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <div>{step === 1 && <Button onClick={goBack} disabled={isCreating}>上一步</Button>}</div>
          <div className="flex gap-2">
            <Button onClick={onClose} disabled={isCreating}>取消</Button>
            {step === 0 ? (
              <Button variant="primary" onClick={goNext}>
                下一步
              </Button>
            ) : (
              <Button variant="primary" type="submit" disabled={isCreating || totalImages === 0}>
                {isCreating ? '创建中…' : `创建案件（${totalImages} 个镜像）`}
              </Button>
            )}
          </div>
        </div>
      </form>
    </Modal>
  );
}
