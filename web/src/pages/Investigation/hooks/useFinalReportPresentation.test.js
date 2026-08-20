import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import {
  getFinalReportHtml,
  getFinalReportMarkdown,
  getFinalReportPrint,
} from '../../../services/investigationService';
import useFinalReportPresentation from './useFinalReportPresentation';

vi.mock('../../../services/investigationService', () => ({
  getFinalReportHtml: vi.fn(),
  getFinalReportMarkdown: vi.fn(),
  getFinalReportPrint: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:report'),
    revokeObjectURL: vi.fn(),
  });
});

test('downloads Markdown for the exact selected report', async () => {
  getFinalReportMarkdown.mockResolvedValue('# Report');
  const originalCreateElement = document.createElement.bind(document);
  let anchor;
  vi.spyOn(document, 'createElement').mockImplementation((tagName, options) => {
    const element = originalCreateElement(tagName, options);
    if (tagName === 'a') {
      element.click = vi.fn();
      anchor = element;
    }
    return element;
  });
  const { result } = renderHook(() => useFinalReportPresentation('task-a', 'report-1', 2, true));

  await act(async () => result.current.downloadMarkdown());

  expect(getFinalReportMarkdown).toHaveBeenCalledWith('task-a', 'report-1');
  expect(anchor.download).toBe('tracelens-report-v2-report-1.md');
  expect(anchor.click).toHaveBeenCalled();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:report');
});

test('creates popup synchronously and prints exact report HTML after response', async () => {
  const targetWindow = { closed: false, document: { open: vi.fn(), write: vi.fn(), close: vi.fn() }, print: vi.fn() };
  const openSpy = vi.spyOn(window, 'open').mockReturnValue(targetWindow);
  getFinalReportPrint.mockResolvedValue('<html>print</html>');
  const { result } = renderHook(() => useFinalReportPresentation('task-a', 'report-2', 4, true));

  await act(async () => result.current.printReport());
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(openSpy).toHaveBeenCalledWith('', '_blank');
  expect(getFinalReportPrint).toHaveBeenCalledWith('task-a', 'report-2');
  expect(targetWindow.document.write).toHaveBeenCalledWith('<html>print</html>');
  expect(targetWindow.print).toHaveBeenCalled();
});

test('closes popup and reports request failure locally', async () => {
  const targetWindow = { closed: false, close: vi.fn() };
  const openSpy = vi.spyOn(window, 'open').mockReturnValue(targetWindow);
  getFinalReportHtml.mockRejectedValue(new Error('network down'));
  const { result } = renderHook(() => useFinalReportPresentation('task-a', 'report-3', 5, true));

  await act(async () => result.current.openHtml());

  expect(openSpy).toHaveBeenCalledWith('', '_blank');
  expect(getFinalReportHtml).toHaveBeenCalledWith('task-a', 'report-3');
  expect(targetWindow.close).toHaveBeenCalled();
  expect(result.current.error).toBe('network down');
});
