import { render, screen, fireEvent } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import ReportOrganizationPanel from './ReportOrganizationPanel';
test('explains preliminary coverage in Chinese without expanding the source list over the body', () => {
  const open=vi.fn();render(<ReportOrganizationPanel organization={{quality:'preliminary',quality_message:'关键结论仍需人工核对',body_chars:8000,appendix_chars:1000,
    plan:{chapters:[{},{},{},{}],finding_disposition:{f1:'正文预算限制'}},validation:{max_section_share:.3},
    findings:[{finding_id:'f1',kind:'hypothesis',statement:'尚不能确认实际使用',counter_spans:['r1']}],
    coverage:[{material_id:'m1',evidence_key:'file:/History',status:'partial',body_status:'appendix',exclusion_reason:'正文预算限制'}],usage:{calls:9},budget:{max_calls:12}}} onOpenMaterial={open}/>);
  expect(screen.getByText('初步研判 · 存在未完成范围')).toBeInTheDocument();
  expect(screen.queryByText('尚不能确认实际使用')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('查看来源与覆盖审计'));
  expect(screen.getByText('尚不能确认实际使用')).toBeInTheDocument();
  fireEvent.click(screen.getByText('file:/History'));expect(open).toHaveBeenCalledWith('m1');
});

test('shows frozen concurrency and qualified whole-report review status', () => {
  render(<ReportOrganizationPanel organization={{quality:'review_required',plan:{chapters:[]},
    validation:{execution_policy:{extraction_concurrency:4,writing_concurrency:2,review_concurrency:2},coherence_status:'auxiliary_checks_passed',
      coherence_advisories:[{section_id:'s1',kind:'repetition',quote:'合成报告的原文片段',reason:'建议压缩重复表述'}]}}}/>);
  fireEvent.click(screen.getByText('查看来源与覆盖审计'));
  expect(screen.getByText(/事实提取 4 路 · 主体写作 2 路 · 逐章复核 2 路/)).toBeInTheDocument();
  expect(screen.getByText(/概述与结论在主体完成后收束/)).toBeInTheDocument();
  expect(screen.getByText(/检查通过，关键结论仍需人工核对/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('全文组织建议 · 1 项'));
  expect(screen.getByText('建议压缩重复表述')).toBeInTheDocument();
});
