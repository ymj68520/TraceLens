import { render, screen, fireEvent } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import DeliveryQualityPanel from './DeliveryQualityPanel';
import VersionHistory from './VersionHistory';
import ReportToolbar from './ReportToolbar';
import IngestionQualityPanel from '../knowledge-graph/IngestionQualityPanel';
import { forensicError, forensicLabel } from '../../utils/forensicLabels';

test('execution complete does not hide partial quality or a failed ingestion item', () => {
  const retry=vi.fn();
  render(<><DeliveryQualityPanel quality={{status:'limited',label:'有范围限制',reasons:['有材料尚未完成提取'],counts:{sources:173,extracted:42,partial:0,deferred:131,unavailable:0}}} />
    <IngestionQualityPanel job={{job_id:'job1',status:'COMPLETED',quality:{status:'limited',label:'有范围限制',total:909,successful:908,failed:1,unprocessed:0,retryable:true}}} onRetry={retry} /></>);
  expect(screen.getByText(/暂缓 131/)).toBeInTheDocument();
  expect(screen.getByText(/成功 908 \/ 总数 909 · 失败 1/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'重试未完成摄取'}));expect(retry).toHaveBeenCalledTimes(1);
});
test('history and toolbar labels are Chinese and actions are wired', () => {
  const html=vi.fn(),history=vi.fn(),bundle=vi.fn();
  render(<><ReportToolbar version={{version:2}} onExportHtml={html} onExportBundle={bundle} onHistory={history}/>
    <VersionHistory versions={[{report_id:'r1',version:1,status:'ready'},{report_id:'r2',version:2,status:'running'}]} onSelect={()=>{}}/></>);
  fireEvent.click(screen.getByRole('button',{name:'导出离线 HTML'}));
  fireEvent.click(screen.getByRole('button',{name:'版本历史'}));
  fireEvent.click(screen.getByRole('button',{name:'下载离线包'}));
  expect(html).toHaveBeenCalledOnce();expect(history).toHaveBeenCalledOnce();expect(bundle).toHaveBeenCalledOnce();
  expect(screen.getByText('已生成')).toBeInTheDocument();expect(screen.getByText('运行中')).toBeInTheDocument();
  expect(forensicError({error_code:'global_report_blocked'})).toContain('未发布');
  expect(forensicError(new Error('secret local path /tmp/token'))).toBe('操作未完成，请重试或查看诊断记录。');
  expect(forensicLabel('Overlay')).toBe('调查图层');
});
test('legacy quality is unassessed and unknown counts are not zero', () => {
  render(<><DeliveryQualityPanel/><IngestionQualityPanel job={{job_id:'old',status:'completed'}}/></>);
  expect(screen.getByText(/本版本没有独立质量记录/)).toBeInTheDocument();
  expect(screen.getByText(/成功 未记录 \/ 总数 未记录/)).toBeInTheDocument();
});
