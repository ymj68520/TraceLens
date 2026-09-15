import { describe, expect, it } from 'vitest';
import {
  custom,
  intRange,
  isInt,
  isValid,
  maxLength,
  minLength,
  pattern,
  required,
  validateForm,
} from '../lib/validation';
import type { FieldRules } from '../lib/validation';

describe('validation rule factories', () => {
  it('required rejects null/undefined/blank values', () => {
    const rule = required('请输入名称');
    expect(rule(null, {})).toBe('请输入名称');
    expect(rule(undefined, {})).toBe('请输入名称');
    expect(rule('', {})).toBe('请输入名称');
    expect(rule('   ', {})).toBe('请输入名称');
  });

  it('required accepts any real value, including 0 and false', () => {
    expect(required()('x', {})).toBeNull();
    expect(required()(0, {})).toBeNull();
    expect(required()(false, {})).toBeNull();
    expect(required()(null, {})).toBe('该项为必填项');
  });

  it('minLength measures the trimmed value and supports a custom message', () => {
    expect(minLength(3)('ab', {})).toBe('至少 3 个字符');
    expect(minLength(3)(' abc ', {})).toBeNull();
    expect(minLength(3, '名称太短')('a', {})).toBe('名称太短');
  });

  it('maxLength measures the raw (untrimmed) value', () => {
    expect(maxLength(3)('abcd', {})).toBe('最多 3 个字符');
    expect(maxLength(3)('abc', {})).toBeNull();
    expect(maxLength(2, '太长了')('abc', {})).toBe('太长了');
  });

  it('pattern skips empty input and validates the rest', () => {
    const rule = pattern(/^\d+$/, '仅限数字');
    expect(rule(null, {})).toBeNull();
    expect(rule('', {})).toBeNull();
    expect(rule('abc', {})).toBe('仅限数字');
    expect(rule('123', {})).toBeNull();
    expect(pattern(/^x$/)('y', {})).toBe('格式不正确');
  });

  it('isInt accepts integer strings (trimmed) and rejects the rest', () => {
    const rule = isInt();
    expect(rule('42', {})).toBeNull();
    expect(rule(' -7 ', {})).toBeNull();
    expect(rule(12, {})).toBeNull();
    expect(rule('1.5', {})).toBe('请输入整数');
    expect(rule('abc', {})).toBe('请输入整数');
    expect(rule(null, {})).toBeNull();
    expect(rule('', {})).toBeNull();
  });

  it('intRange bounds numeric input and skips empty values', () => {
    const rule = intRange(1, 100);
    expect(rule(1, {})).toBeNull();
    expect(rule('100', {})).toBeNull();
    expect(rule('0', {})).toBe('请输入 1–100 之间的整数');
    expect(rule(101, {})).toBe('请输入 1–100 之间的整数');
    expect(rule('2.5', {})).toBe('请输入 1–100 之间的整数');
    expect(intRange(1, 10, '端口超出范围')(99, {})).toBe('端口超出范围');
    expect(rule(null, {})).toBeNull();
    expect(rule('', {})).toBeNull();
  });

  it('custom is the rule itself and can compare across fields', () => {
    const rule = custom((v, all) => (v === all.password ? null : '两次输入不一致'));
    expect(rule('secret', { password: 'secret' })).toBeNull();
    expect(rule('other', { password: 'secret' })).toBe('两次输入不一致');
  });
});

interface DemoForm {
  name: string;
  port: string;
  note: string;
}

describe('validateForm', () => {
  const rules: FieldRules<DemoForm> = {
    name: [required('名称必填'), minLength(2, '名称至少 2 个字符')],
    port: [isInt(), intRange(1, 65535)],
  };

  it('returns the first failing message per field', () => {
    expect(validateForm(rules, { name: '', port: 'x', note: '' })).toEqual({
      name: '名称必填',
      port: '请输入整数',
    });
  });

  it('short-circuits within a field — later rules do not run', () => {
    const errors = validateForm(rules, { name: 'a', port: '99999', note: '' });
    expect(errors).toEqual({
      name: '名称至少 2 个字符',
      port: '请输入 1–65535 之间的整数',
    });
  });

  it('passes the whole value object into custom rules', () => {
    const pairRules: FieldRules<{ password: string; confirm: string }> = {
      confirm: [custom((v, all) => (v === all.password ? null : '两次输入不一致'))],
    };
    expect(validateForm(pairRules, { password: 'x', confirm: 'x' })).toEqual({});
    expect(validateForm(pairRules, { password: 'x', confirm: 'y' })).toEqual({
      confirm: '两次输入不一致',
    });
  });

  it('omits passing fields from the result', () => {
    expect(validateForm(rules, { name: 'abc', port: '8080', note: '' })).toEqual({});
  });

  it('ignores fields with empty rule arrays', () => {
    expect(validateForm({ note: [] }, { name: '', port: '', note: '' })).toEqual({});
  });
});

describe('isValid', () => {
  it('is true only when every message is empty', () => {
    expect(isValid({})).toBe(true);
    expect(isValid({ name: undefined, port: '' })).toBe(true);
    expect(isValid({ name: '错误' })).toBe(false);
    expect(isValid({ name: undefined, port: '端口错误' })).toBe(false);
  });
});
