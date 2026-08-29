import { useState, type FormEvent } from 'react';
import { useAppDispatch } from '../../store';
import { createTask, fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import { errorMessage } from '../../lib/utils';

/**
 * Task creation form. LLM analysis is always on (not a user toggle); a
 * logical Android source (dir/zip/miui-backup) forces the android scenario
 * and bypasses the TSK disk pipeline entirely.
 */
const DATA_SOURCES = [
  { value: 'tsk', label: '磁盘镜像', desc: '.dd / .E01 / raw 镜像（TSK 文件系统解析）' },
  { value: 'dir', label: 'Android 目录', desc: '已解压的逻辑提取目录树' },
  { value: 'zip', label: 'Android ZIP', desc: '逻辑提取打包成的单个 .zip' },
  { value: 'miui-backup', label: 'MIUI 备份', desc: '小米 MIUI 离线备份目录（descript.xml + .bak）' },
] as const;

interface FormState {
  image_path: string;
  android_source: string;
  backup_password: string;
  priority: string;
  case_description: string;
  xfs_mode: string;
}

const INITIAL_FORM: FormState = {
  image_path: '',
  android_source: 'tsk',
  backup_password: '',
  priority: 'normal',
  case_description: '',
  xfs_mode: 'auto',
};

export default function CreateTaskModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dispatch = useAppDispatch();
  const toast = useToast();

  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const set = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: val }));

  const isLogical = form.android_source !== 'tsk';
  const isMiui = form.android_source === 'miui-backup';

  const pathLabel = isMiui
    ? 'MIUI 备份目录 *'
    : form.android_source === 'dir'
      ? 'Android 提取目录 *'
      : form.android_source === 'zip'
        ? 'Android ZIP 文件 *'
        : '镜像路径 *';
  const pathPlaceholder = isMiui
    ? '/path/to/MIUI备份目录（含 descript.xml + .bak）'
    : form.android_source === 'dir'
      ? '/path/to/android_logical_extraction/'
      : form.android_source === 'zip'
        ? '/path/to/android_extraction.zip'
        : '/path/to/disk_image.dd 或 /path/to/image.E01';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setIsCreating(true);
    try {
      const payload: Record<string, unknown> = {
        ...form,
        scenarios: isLogical ? ['android'] : [],
        llm_analyze: true,
        llm_mode: 'smart',
      };
      if (!payload.backup_password) delete payload.backup_password;
      await dispatch(createTask(payload as never)).unwrap();
      onClose();
      setForm(INITIAL_FORM);
      void dispatch(fetchTasks({}));
      toast.success('任务创建成功');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="新建分析任务" width="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}

        <div>
          <span className="field-label">数据源类型</span>
          <div className="grid grid-cols-2 gap-2">
            {DATA_SOURCES.map((ds) => (
              <label
                key={ds.value}
                className={`flex flex-col gap-0.5 px-3 py-2 rounded-md border cursor-pointer transition-colors ${
                  form.android_source === ds.value
                    ? 'border-accent-500 bg-accent-50 dark:bg-accent-500/10'
                    : 'border-ink-200 dark:border-ink-700 hover:border-ink-300'
                }`}
              >
                <input
                  type="radio"
                  name="android_source"
                  value={ds.value}
                  checked={form.android_source === ds.value}
                  onChange={(e) => set('android_source', e.target.value)}
                  className="sr-only"
                />
                <span className="text-sm font-medium text-ink-800 dark:text-ink-100">{ds.label}</span>
                <span className="text-2xs text-ink-500 dark:text-ink-400">{ds.desc}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="field-label" htmlFor="task-path">{pathLabel}</label>
          <input
            id="task-path"
            type="text"
            required
            value={form.image_path}
            onChange={(e) => set('image_path', e.target.value)}
            className="input font-mono text-xs"
            placeholder={pathPlaceholder}
          />
        </div>

        <div>
          <label className="field-label" htmlFor="task-desc">案情描述 *</label>
          <textarea
            id="task-desc"
            required
            rows={3}
            value={form.case_description}
            onChange={(e) => set('case_description', e.target.value)}
            className="input resize-y"
            placeholder="简要描述案情背景，LLM 分析将以此为导向…"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="field-label" htmlFor="task-priority">优先级</label>
            <select
              id="task-priority"
              value={form.priority}
              onChange={(e) => set('priority', e.target.value)}
              className="select"
            >
              <option value="low">低</option>
              <option value="normal">普通</option>
              <option value="high">高</option>
              <option value="critical">紧急</option>
            </select>
          </div>
          {isMiui && (
            <div>
              <label className="field-label" htmlFor="task-backup-pw">备份密码（可选）</label>
              <input
                id="task-backup-pw"
                type="password"
                value={form.backup_password}
                onChange={(e) => set('backup_password', e.target.value)}
                className="input"
                placeholder="MIUI 备份加密密码"
                autoComplete="off"
              />
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-xs text-accent-600 dark:text-accent-400 hover:underline"
        >
          {showAdvanced ? '收起高级选项 ▴' : '高级选项 ▾'}
        </button>

        {showAdvanced && !isLogical && (
          <div>
            <label className="field-label" htmlFor="task-xfs">XFS 时间戳模式</label>
            <select
              id="task-xfs"
              value={form.xfs_mode}
              onChange={(e) => set('xfs_mode', e.target.value)}
              className="select"
            >
              <option value="auto">自动</option>
              <option value="v4">XFS v4</option>
              <option value="v5">XFS v5</option>
            </select>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={isCreating}>取消</Button>
          <Button variant="primary" type="submit" disabled={isCreating}>
            {isCreating ? '创建中…' : '创建任务'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
