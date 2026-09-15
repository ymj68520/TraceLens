/**
 * Tiny declarative form-validation layer. Rules are plain functions so any
 * field type composes; `validateForm` maps a rule set onto form values and
 * returns per-field messages for FormField to render.
 *
 *   const rules: FieldRules<Form> = {
 *     name: [required('请输入名称'), minLength(2, '至少 2 个字符')],
 *     port: [custom((v) => Number(v) > 0 || '端口必须为正数')],
 *   };
 *   const errors = validateForm(rules, values); // { name?: string; port?: string }
 */

export type Validator = (value: unknown, allValues: Record<string, unknown>) => string | null;

export type FieldRules<T> = Partial<{ [K in keyof T]: Validator[] }>;

export function required(message = '该项为必填项'): Validator {
  return (v) => (v == null || String(v).trim() === '' ? message : null);
}

export function minLength(n: number, message?: string): Validator {
  return (v) => (v != null && String(v).trim().length < n ? message ?? `至少 ${n} 个字符` : null);
}

export function maxLength(n: number, message?: string): Validator {
  return (v) => (v != null && String(v).length > n ? message ?? `最多 ${n} 个字符` : null);
}

export function pattern(re: RegExp, message = '格式不正确'): Validator {
  return (v) => (v == null || v === '' || re.test(String(v)) ? null : message);
}

export function isInt(message = '请输入整数'): Validator {
  return (v) => (v == null || v === '' || /^-?\d+$/.test(String(v).trim()) ? null : message);
}

export function intRange(min: number, max: number, message?: string): Validator {
  return (v) => {
    if (v == null || v === '') return null;
    const n = Number(v);
    if (!Number.isInteger(n) || n < min || n > max) return message ?? `请输入 ${min}–${max} 之间的整数`;
    return null;
  };
}

export function custom(fn: (value: unknown, allValues: Record<string, unknown>) => string | null): Validator {
  return fn;
}

/** Run every rule; return the first message per field (only failing fields). */
export function validateForm<T extends Record<string, unknown>>(
  rules: FieldRules<T>,
  values: T,
): Partial<Record<keyof T, string>> {
  const errors: Partial<Record<keyof T, string>> = {};
  for (const key of Object.keys(rules) as (keyof T)[]) {
    const fieldRules = rules[key];
    if (!fieldRules) continue;
    for (const rule of fieldRules) {
      const message = rule(values[key], values);
      if (message) {
        errors[key] = message;
        break;
      }
    }
  }
  return errors;
}

/** True when the error map has no entries. */
export const isValid = (errors: Record<string, string | undefined>): boolean =>
  Object.values(errors).every((m) => !m);
