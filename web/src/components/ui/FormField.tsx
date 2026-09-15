import type { ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';
import { cn } from '../../lib/utils';

/**
 * Labeled form field with inline error message. Compose with .input/.select:
 *
 *   <FormField label="任务名称" error={errors.name} hint="用于案件内展示">
 *     <input className="input" ... />
 *   </FormField>
 */
export function FormField({
  label,
  error,
  hint,
  required: requiredMark = false,
  children,
  className,
  htmlFor,
}: {
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <label className="field-label flex items-center gap-1" htmlFor={htmlFor}>
        {label}
        {requiredMark && <span className="text-rose-500" aria-hidden>*</span>}
      </label>
      {children}
      {error ? (
        <p className="mt-1.5 flex items-center gap-1 text-2xs text-rose-600 dark:text-rose-400 animate-fade-in" role="alert">
          <AlertCircle size={11} className="shrink-0" />
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1.5 text-2xs text-ink-400 dark:text-ink-500">{hint}</p>
      ) : null}
    </div>
  );
}

export default FormField;
