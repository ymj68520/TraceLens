import { useState } from 'react';
import Modal from '../../components/ui/Modal';
import FormField from '../../components/ui/FormField';
import Button from '../../components/ui/Button';
import ProgressBar from '../../components/ui/ProgressBar';
import { maxLength, required, isValid, validateForm, type FieldRules } from '../../lib/validation';

export type ReportExportFormat = 'json' | 'markdown' | 'none';

export type GenerateFormValues = {
  requestedBy: string;
  format: ReportExportFormat;
};

interface Props {
  open: boolean;
  /** Task scope the report is generated for (read-only, fixed by context). */
  scopeLabel: string;
  submitting: boolean;
  progress: number;
  onSubmit: (values: GenerateFormValues) => void;
  onClose: () => void;
}

// R2c freeze: the generate API only accepts task scope + requested_by, so the
// format choice is a local export preference applied after generation.
const RULES: FieldRules<GenerateFormValues> = {
  requestedBy: [required('请输入申请人'), maxLength(40, '申请人不能超过 40 个字符')],
};

const FORMAT_OPTIONS: { value: ReportExportFormat; label: string }[] = [
  { value: 'json', label: 'JSON 文件' },
  { value: 'markdown', label: 'Markdown 文件' },
  { value: 'none', label: '暂不导出' },
];

/** Regenerate dialog: validated 申请人 + post-generation export format. */
export default function GenerateReportModal({
  open,
  scopeLabel,
  submitting,
  progress,
  onSubmit,
  onClose,
}: Props) {
  const [values, setValues] = useState<GenerateFormValues>({ requestedBy: '', format: 'json' });
  const [errors, setErrors] = useState<Partial<Record<keyof GenerateFormValues, string>>>({});

  const setField = (patch: Partial<GenerateFormValues>) => {
    setValues((prev) => ({ ...prev, ...patch }));
    setErrors({});
  };

  const handleSubmit = () => {
    const next = validateForm(RULES, values);
    setErrors(next);
    if (isValid(next)) {
      onSubmit({ requestedBy: values.requestedBy.trim(), format: values.format });
    }
  };

  return (
    <Modal open={open} onClose={submitting ? () => {} : onClose} title="生成取证报告">
      <div className="space-y-4">
        <FormField label="目标任务" required hint="报告基于该任务已完成的取证分析结果生成">
          <input className="input font-mono text-xs" value={scopeLabel} disabled readOnly />
        </FormField>

        <FormField label="申请人" required error={errors.requestedBy} hint="记录到报告生成的审计信息中" htmlFor="gen-requested-by">
          <input
            id="gen-requested-by"
            className="input"
            placeholder="如：张三 / 分析员A"
            value={values.requestedBy}
            disabled={submitting}
            onChange={(e) => setField({ requestedBy: e.target.value })}
          />
        </FormField>

        <FormField label="完成后导出格式" hint="生成完成后自动在本地下载该格式，不影响服务端生成">
          <select
            className="select"
            value={values.format}
            disabled={submitting}
            onChange={(e) => setField({ format: e.target.value as ReportExportFormat })}
          >
            {FORMAT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FormField>

        {submitting && (
          <div>
            <p className="text-2xs text-ink-500 dark:text-ink-400 mb-1.5">正在生成报告，请勿关闭页面…</p>
            <ProgressBar value={progress} showLabel />
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button variant="primary" size="sm" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '生成中…' : '开始生成'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
