import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import useInitialAnalysisTranslation, {
  initialAnalysisText,
  needsChineseTranslation,
} from './useInitialAnalysisTranslation';
import { translateInitialAnalysis } from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({
  translateInitialAnalysis: vi.fn(),
}));

beforeEach(() => vi.clearAllMocks());

test('combines distinct snapshot summary and description for complete translation', () => {
  expect(initialAnalysisText({ initial_summary: 'Summary', initial_description: 'Description' }))
    .toBe('摘要：Summary\n\n详细描述：Description');
  expect(initialAnalysisText({ initial_summary: 'Same', initial_description: 'Same' })).toBe('Same');
  expect(needsChineseTranslation('SUMMARY: This file contains a deletion rule for the user application folder.')).toBe(true);
  expect(needsChineseTranslation('该文件记录了用户目录中的清理规则。')).toBe(false);
});

test('does not let an old evidence translation overwrite the newly selected evidence', async () => {
  let resolveOld;
  translateInitialAnalysis.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }));
  const oldText = 'SUMMARY: This file contains a long English description about cleanup settings.';
  const { result, rerender } = renderHook(
    ({ evidenceKey, text }) => useInitialAnalysisTranslation('task', evidenceKey, text),
    { initialProps: { evidenceKey: 'file:/old.txt', text: oldText } },
  );
  await waitFor(() => expect(result.current.loading).toBe(true));
  rerender({ evidenceKey: 'file:/new.txt', text: '该文件属于新证据。' });
  await waitFor(() => expect(result.current.text).toBe('该文件属于新证据。'));
  await act(async () => resolveOld({ text: '过期译文', translated: true }));
  expect(result.current.text).toBe('该文件属于新证据。');
});
