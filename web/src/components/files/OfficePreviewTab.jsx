// OfficePreviewTab.jsx
// "Office 预览" tab: pick an Office file (.pptx/.xlsx/.docx) and render parsed
// slides / sheets / raw text. Parsing state is owned by the parent.

import Card from '../common/Card';
import Badge from '../common/Badge';
import Spinner from '../common/Spinner';
import { parseFile } from '../../services/officeService';

const OFFICE_EXTENSIONS = ['.pptx', '.ppt', '.xlsx', '.xls'];

const OfficePreviewTab = ({
  taskId,
  filteredFiles,
  officePreview,
  setOfficePreview,
  officeParsing,
  setOfficeParsing,
  officeError,
  setOfficeError,
}) => {
  const officeFiles = filteredFiles.filter((f) =>
    OFFICE_EXTENSIONS.includes((f.extension || '').toLowerCase())
  );

  const handlePick = async (file, filePath) => {
    setOfficeParsing(true);
    setOfficeError(null);
    setOfficePreview(null);
    try {
      const result = await parseFile(taskId, filePath);
      setOfficePreview({ file, ...result });
    } catch (err) {
      setOfficeError(err.message || '解析失败');
    } finally {
      setOfficeParsing(false);
    }
  };

  return (
    <Card title="📄 Office 文档预览">
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          选择一个 Office 文件 (PPT, Excel) 解析并预览内容。支持 .pptx, .xlsx, .xls 格式。
        </p>
        {/* File selector for Office files */}
        <div className="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700">
          <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">选择文件</h4>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {officeFiles.map((file, idx) => {
              const filePath = file.path || file.file_path;
              return (
                <button
                  key={idx}
                  onClick={() => handlePick(file, filePath)}
                  disabled={officeParsing}
                  className="w-full text-left px-3 py-2 rounded hover:bg-blue-50 dark:hover:bg-blue-900/20 text-sm text-slate-700 dark:text-slate-300 flex items-center gap-2"
                >
                  <Badge variant="blue">{file.extension}</Badge>
                  <span className="truncate">{file.name || filePath?.split('/').pop()}</span>
                </button>
              );
            })}
            {officeFiles.length === 0 && (
              <p className="text-slate-400 text-sm py-4 text-center">无 Office 文件</p>
            )}
          </div>
        </div>

        {officeParsing && (
          <div className="flex items-center justify-center py-8">
            <Spinner size="lg" />
            <span className="ml-3 text-slate-600 dark:text-slate-300">解析中...</span>
          </div>
        )}

        {officeError && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded text-sm">
            ❌ {officeError}
          </div>
        )}

        {officePreview && (
          <div className="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700">
            <h4 className="font-medium text-slate-900 dark:text-white mb-3">
              📄 {officePreview.file?.name || '文档内容'}
            </h4>
            {/* Structured content takes precedence; the API's Markdown content is the fallback. */}
            {officePreview.slides && (
              <div className="space-y-3">
                <p className="text-sm text-slate-500">幻灯片: {officePreview.slides.length} 页</p>
                {officePreview.slides.map((slide, i) => (
                  <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                    <p className="text-xs text-slate-400 mb-1">第 {i + 1} 页</p>
                    <p className="text-sm text-slate-800 dark:text-slate-200 whitespace-pre-wrap">{slide.text || slide.content || '(无文本)'}</p>
                  </div>
                ))}
              </div>
            )}
            {officePreview.sheets && (
              <div className="space-y-3">
                <p className="text-sm text-slate-500">工作表: {officePreview.sheets.length} 个</p>
                {officePreview.sheets.map((sheet, i) => (
                  <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                    <p className="text-xs text-slate-400 mb-1">{sheet.name || `工作表 ${i + 1}`}</p>
                    {sheet.data && sheet.data.length > 0 ? (
                      <div className="overflow-x-auto">
                        <table className="text-xs">
                          <tbody>
                            {sheet.data.slice(0, 20).map((row, ri) => (
                              <tr key={ri}>
                                {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                                  <td key={ci} className="px-2 py-1 border border-slate-200 dark:border-slate-600">{String(cell ?? '')}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {sheet.data.length > 20 && <p className="text-xs text-slate-400 mt-1">… 还有 {sheet.data.length - 20} 行</p>}
                      </div>
                    ) : (
                      <p className="text-sm text-slate-400">(无数据)</p>
                    )}
                  </div>
                ))}
              </div>
            )}
            {officePreview.content && !officePreview.slides && !officePreview.sheets && !officePreview.text && (
              <pre className="text-sm text-slate-800 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                {officePreview.content}
              </pre>
            )}
            {/* Raw text compatibility fallback */}
            {officePreview.text && !officePreview.slides && !officePreview.sheets && (
              <pre className="text-sm text-slate-800 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                {officePreview.text}
              </pre>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};

export default OfficePreviewTab;
