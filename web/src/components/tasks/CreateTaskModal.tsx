import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { useAppDispatch } from '../../store';
import { createTask, fetchTasks } from '../../store/taskSlice';
import { useToast } from '../ui/Toast';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import FormField from '../ui/FormField';
import { emitAppEvent } from '../../lib/appEvents';
import { basename, errorMessage } from '../../lib/utils';
import { required, custom, validateForm, isValid, type FieldRules } from '../../lib/validation';
import { useTranslation } from '../../hooks/useTranslation';
import type { TranslationKey } from '../../locales/keys';

/**
 * Task creation form. LLM analysis is always on (not a user toggle); a
 * logical Android source (dir/zip/miui-backup) forces the android scenario
 * and bypasses the TSK disk pipeline entirely.
 */
const DATA_SOURCES = [
  {
    value: 'tsk',
    labelKey: 'task.create.source.tsk',
    descKey: 'task.create.source.tsk_desc',
  },
  {
    value: 'dir',
    labelKey: 'task.create.source.dir',
    descKey: 'task.create.source.dir_desc',
  },
  {
    value: 'zip',
    labelKey: 'task.create.source.zip',
    descKey: 'task.create.source.zip_desc',
  },
  {
    value: 'miui-backup',
    labelKey: 'task.create.source.miui',
    descKey: 'task.create.source.miui_desc',
  },
] as const satisfies ReadonlyArray<{
  value: FormState['android_source'];
  labelKey: TranslationKey;
  descKey: TranslationKey;
}>;

const PATH_LABEL_KEY: Record<FormState['android_source'], TranslationKey> = {
  tsk: 'task.create.path_label.tsk',
  dir: 'task.create.path_label.dir',
  zip: 'task.create.path_label.zip',
  'miui-backup': 'task.create.path_label.miui',
};

const PATH_PLACEHOLDER_KEY: Record<FormState['android_source'], TranslationKey> = {
  tsk: 'task.create.path_placeholder.tsk',
  dir: 'task.create.path_placeholder.dir',
  zip: 'task.create.path_placeholder.zip',
  'miui-backup': 'task.create.path_placeholder.miui',
};

/** Absolute POSIX path per line: something after a leading "/". */
const ABSOLUTE_PATH_RE = /^\/.+/;

const splitPaths = (value: string): string[] =>
  value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

// Type alias (not interface) so FormState carries an implicit index signature
// and satisfies validateForm's `T extends Record<string, unknown>` bound.
type FormState = {
  image_path: string;
  android_source: string;
  backup_password: string;
  priority: string;
  case_description: string;
  xfs_mode: string;
};

const INITIAL_FORM: FormState = {
  image_path: '',
  android_source: 'tsk',
  backup_password: '',
  priority: 'normal',
  case_description: '',
  xfs_mode: 'auto',
};

/** Validation order doubles as the focus order for the first failing field. */
const VALIDATED_FIELD_ORDER = ['image_path', 'case_description'] as const;

export default function CreateTaskModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dispatch = useAppDispatch();
  const toast = useToast();
  const { t } = useTranslation();

  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  // Field errors only surface after a submit attempt; editing then re-validates live.
  const [submitted, setSubmitted] = useState(false);

  const pathRef = useRef<HTMLTextAreaElement>(null);
  const descRef = useRef<HTMLTextAreaElement>(null);
  const fieldRefs: Partial<Record<keyof FormState, RefObject<HTMLTextAreaElement>>> = {
    image_path: pathRef,
    case_description: descRef,
  };

  const set = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: val }));

  // Closing the modal clears the validation state; the form itself resets on success.
  useEffect(() => {
    if (!open) setSubmitted(false);
  }, [open]);

  const rules: FieldRules<FormState> = {
    image_path: [
      required(t('task.create.error.path_required')),
      custom((v) =>
        splitPaths(String(v ?? '')).every((line) => ABSOLUTE_PATH_RE.test(line))
          ? null
          : t('task.create.error.path_format'),
      ),
    ],
    case_description: [required(t('task.create.error.desc_required'))],
  };

  const errors = validateForm(rules, form);
  const errorCount = Object.values(errors).filter(Boolean).length;
  const fieldError = (key: keyof FormState): string | undefined =>
    submitted ? errors[key] : undefined;

  const isLogical = form.android_source !== 'tsk';
  const isMiui = form.android_source === 'miui-backup';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!isValid(errors)) {
      const first = VALIDATED_FIELD_ORDER.find((key) => errors[key]);
      if (first) fieldRefs[first]?.current?.focus();
      return;
    }
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
      setSubmitted(false);
      void dispatch(fetchTasks({}));
      toast.success(t('task.create.toast_success'));
      emitAppEvent({
        kind: 'success',
        title: t('task.create.event_title'),
        detail: basename(splitPaths(form.image_path)[0]),
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={t('task.create.title')} width="lg">
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        {/* Request-level error (backend failure) */}
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}

        {/* Validation summary bar */}
        {submitted && errorCount > 0 && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-rose-200 dark:border-rose-500/20 bg-rose-50 dark:bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-600 dark:text-rose-400"
          >
            <AlertCircle size={14} className="shrink-0" />
            {t('task.create.error.summary').replace('{n}', String(errorCount))}
          </div>
        )}

        <FormField label={t('task.create.source_type')}>
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
                <span className="text-sm font-medium text-ink-800 dark:text-ink-100">
                  {t(ds.labelKey)}
                </span>
                <span className="text-2xs text-ink-500 dark:text-ink-400">{t(ds.descKey)}</span>
              </label>
            ))}
          </div>
        </FormField>

        <FormField
          label={t(PATH_LABEL_KEY[form.android_source])}
          htmlFor="task-path"
          required
          error={fieldError('image_path')}
          hint={t('task.create.path_hint')}
        >
          <textarea
            id="task-path"
            ref={pathRef}
            rows={3}
            value={form.image_path}
            onChange={(e) => set('image_path', e.target.value)}
            className="input font-mono text-xs resize-y"
            aria-invalid={Boolean(fieldError('image_path'))}
            placeholder={t(PATH_PLACEHOLDER_KEY[form.android_source])}
          />
        </FormField>

        <FormField
          label={t('task.create.desc_label')}
          htmlFor="task-desc"
          required
          error={fieldError('case_description')}
        >
          <textarea
            id="task-desc"
            ref={descRef}
            rows={3}
            value={form.case_description}
            onChange={(e) => set('case_description', e.target.value)}
            className="input resize-y"
            aria-invalid={Boolean(fieldError('case_description'))}
            placeholder={t('task.create.desc_placeholder')}
          />
        </FormField>

        <div className="grid grid-cols-2 gap-3">
          <FormField label={t('task.create.priority_label')} htmlFor="task-priority">
            <select
              id="task-priority"
              value={form.priority}
              onChange={(e) => set('priority', e.target.value)}
              className="select"
            >
              <option value="low">{t('task.priority.low')}</option>
              <option value="normal">{t('task.priority.normal')}</option>
              <option value="high">{t('task.priority.high')}</option>
              <option value="critical">{t('task.priority.critical')}</option>
            </select>
          </FormField>
          {isMiui && (
            <FormField
              label={t('task.create.backup_pw_label')}
              htmlFor="task-backup-pw"
            >
              <input
                id="task-backup-pw"
                type="password"
                value={form.backup_password}
                onChange={(e) => set('backup_password', e.target.value)}
                className="input"
                placeholder={t('task.create.backup_pw_placeholder')}
                autoComplete="off"
              />
            </FormField>
          )}
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-xs text-accent-600 dark:text-accent-400 hover:underline"
        >
          {showAdvanced ? t('task.create.advanced_collapse') : t('task.create.advanced')}
        </button>

        {showAdvanced && !isLogical && (
          <FormField label={t('task.create.xfs_label')} htmlFor="task-xfs">
            <select
              id="task-xfs"
              value={form.xfs_mode}
              onChange={(e) => set('xfs_mode', e.target.value)}
              className="select"
            >
              <option value="auto">{t('task.create.xfs.auto')}</option>
              <option value="v4">{t('task.create.xfs.v4')}</option>
              <option value="v5">{t('task.create.xfs.v5')}</option>
            </select>
          </FormField>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t border-ink-100 dark:border-ink-800">
          <Button onClick={onClose} disabled={isCreating}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" disabled={isCreating}>
            {isCreating ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                {t('task.create.submitting')}
              </>
            ) : (
              t('task.create.submit')
            )}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
