/**
 * Translation key typing for the i18n layer.
 *
 * zh.ts is the base locale: `typeof zh` keeps its literal dot-namespaced keys
 * (declared with `satisfies LocaleDict` instead of a wide annotation), so the
 * union below is derived from the real dictionary and never drifts from it.
 * en.ts is annotated `Record<TranslationKey, string>`, which makes any key-set
 * mismatch between the two locales a compile error.
 *
 * `useTranslation` accepts `TranslationKey | (string & {})`: literal keys get
 * autocomplete and typo checking, while arbitrary strings (e.g. dynamic
 * `` `task.status.${status}` `` templates) remain assignable so wide call
 * sites keep compiling.
 */
import type zh from './zh';

export type TranslationKey = keyof typeof zh;
