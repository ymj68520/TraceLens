/**
 * AnalysisBudgetField — task-level LLM analysis file budget.
 *
 * The number the user picks becomes the task's `llm_max_files`, and that one
 * value bounds the whole cost curve: per-file LLM analysis, the knowledge
 * graph ingestion (which ingests analyzed files only) and the report evidence
 * seed (same analyzed-file scope). "使用系统默认" omits the field so the
 * server falls back to its global LLM_MAX_FILES.
 *
 * Shared by CreateTaskModal and CreateCaseModal so both task-creation entry
 * points offer the same choices and the same validation.
 */
import { useId } from 'react';

export const BUDGET_MAX = 100000;
export const BUDGET_PRESETS = ['100', '300', '500', '1000'];

export const DEFAULT_BUDGET_CHOICE = 'default';

/**
 * Resolve the picker state into a payload value.
 * @returns {{value: number}|{error: string}} `undefined` value means omit.
 */
export function resolveAnalysisBudget(choice, customValue) {
  if (choice === DEFAULT_BUDGET_CHOICE) return { value: undefined };
  if (choice !== 'custom') return { value: Number(choice) };
  const trimmed = String(customValue ?? '').trim();
  if (!/^\d+$/.test(trimmed)) {
    return { error: '分析文件上限需填写正整数，或选择“使用系统默认”' };
  }
  const value = Number(trimmed);
  if (value < 1 || value > BUDGET_MAX) {
    return { error: `分析文件上限需在 1–${BUDGET_MAX} 之间` };
  }
  return { value };
}

export function budgetChoiceFromTask(task) {
  const existing = Number(task?.llm_max_files);
  if (existing > 0) return 'custom';
  return DEFAULT_BUDGET_CHOICE;
}

export function customBudgetFromTask(task) {
  const existing = Number(task?.llm_max_files);
  return existing > 0 ? String(existing) : '';
}

const inputCls =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';

export default function AnalysisBudgetField({
  choice,
  onChoiceChange,
  customValue,
  onCustomChange,
  disabled = false,
  showDisabledHint = false,
}) {
  const selectId = useId();
  const inputId = useId();

  return (
    <div>
      <label htmlFor={selectId} className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
        分析文件上限
      </label>
      <select
        id={selectId}
        disabled={disabled}
        value={choice}
        onChange={(e) => onChoiceChange(e.target.value)}
        className={inputCls}
      >
        <option value={DEFAULT_BUDGET_CHOICE}>使用系统默认</option>
        {BUDGET_PRESETS.map((v) => (
          <option key={v} value={v}>{v} 个文件</option>
        ))}
        <option value="custom">自定义…</option>
      </select>
      {choice === 'custom' && (
        <input
          id={inputId}
          type="number"
          min={1}
          max={BUDGET_MAX}
          step={1}
          disabled={disabled}
          value={customValue}
          onChange={(e) => onCustomChange(e.target.value)}
          className={`${inputCls} mt-2`}
          placeholder={`输入 1–${BUDGET_MAX} 之间的整数`}
          aria-label="自定义分析文件上限"
        />
      )}
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        决定逐文件 LLM 分析与知识图谱摄取的文件数；越少越快，但可能漏掉证据。智能模式下按取证价值优先挑选。
      </p>
      {showDisabledHint && (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          仅对本次新建任务生效；已有关联任务沿用其原有预算。
        </p>
      )}
    </div>
  );
}
