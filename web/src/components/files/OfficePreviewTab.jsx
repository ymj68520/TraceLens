// OfficePreviewTab.jsx
// "Office 预览" tab: pick an Office file (.docx/.doc/.pptx/.xlsx/...) and render
// parsed text content. Parsing state is owned by the parent.
// 文件列表由本组件自取（paged 端点 + 扩展名过滤），不依赖父级的文件列表页数据。

import { useEffect, useState } from 'react';
import Card from '../common/Card';
import Badge from '../common/Badge';
import Spinner from '../common/Spinner';
import DocxPreview from './DocxPreview';
import { parseFile } from '../../services/officeService';
import api from '../../services/api';

const OFFICE_EXTENSIONS = ['.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls'];

const OfficePreviewTab = ({
  taskId,
  officePreview,
  setOfficePreview,
  officeParsing,
  setOfficeParsing,
  officeError,
  setOfficeError,
}) => {
  const [officeFiles, setOfficeFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [listError, setListError] = useState(null);

  // 挂载/换任务时拉取该任务的全部 Office 文档（documents 视图 + 扩展名白名单）
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    setLoadingFiles(true);
    setListError(null);
    api
      // 逗号分隔的 extension 必须保持原样（crow 不解码 %2C），因此手动拼 query
      .get(`/api/forensics/files/paged?task_id=${encodeURIComponent(taskId)}&view=documents&extension=${OFFICE_EXTENSIONS.join(',')}&page=1&page_size=200`)
      .then((res) => {
        if (cancelled) return;
        // api 拦截器已剥掉 axios response，这里 res 就是 {files: [...]} 本体
        const rows = res?.files || res?.items || [];
        const seen = new Set();
        const unique = rows.filter((f) => {
          const key = f.path || f.file_path || f.name;
          if (!key || seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        setOfficeFiles(unique);
      })
      .catch((err) => {
        if (!cancelled) setListError(err?.response?.data?.error || err.message || '加载文件列表失败');
      })
      .finally(() => {
        if (!cancelled) setLoadingFiles(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const handlePick = async (file, filePath) => {
    setOfficeParsing(true);
    setOfficeError(null);
    setOfficePreview(null);
    try {
      const result = await parseFile(taskId, filePath);
      // 解析器返回 200 但 success=false 时（如文件损坏），把 error 提为失败。
      if (result && result.success === false) {
        setOfficeError(result.error || '解析失败');
      } else {
        setOfficePreview({ file, filePath, ...result });
      }
    } catch (err) {
      setOfficeError(err?.response?.data?.detail || err.message || '解析失败');
    } finally {
      setOfficeParsing(false);
    }
  };

  return (
    <Card title="📄 Office 文档预览">
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          选择一个 Office 文件 (Word, PPT, Excel) 解析并预览文本内容。支持 .docx, .doc, .pptx, .ppt, .xlsx, .xls 格式。
        </p>
        {/* File selector for Office files */}
        <div className="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700">
          <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">选择文件</h4>
          {loadingFiles && (
            <div className="flex items-center justify-center gap-2 py-4 text-slate-400 text-sm">
              <Spinner size="sm" /> 加载文件列表...
            </div>
          )}
          {listError && (
            <p className="text-red-500 text-sm py-2">❌ {listError}</p>
          )}
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
                  {file.is_deleted ? <Badge variant="red">已删除</Badge> : null}
                  <span className="truncate">{file.name || filePath?.split('/').pop()}</span>
                </button>
              );
            })}
            {!loadingFiles && officeFiles.length === 0 && !listError && (
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
            {/* DOCX gets a full-fidelity in-browser render; other formats
                show structured slides/sheets, falling back to raw text. */}
            {officePreview.file_type === 'DOCX' ? (
              <DocxPreview
                taskId={taskId}
                filePath={officePreview.filePath}
                fallbackText={officePreview.content}
              />
            ) : (
              <>
                {officePreview.slides && (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-500">幻灯片: {officePreview.slides.length} 页</p>
                    {officePreview.slides.map((slide, i) => (
                      <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                        <p className="text-xs text-slate-400 mb-1">第 {i + 1} 页</p>
                        {slide.title && (
                          <p className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-1">{slide.title}</p>
                        )}
                        {(slide.texts || []).map((text, j) => (
                          <p key={j} className="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">{text}</p>
                        ))}
                        {(slide.images || []).map((src, j) => (
                          <img key={j} src={src} alt={`第 ${i + 1} 页插图 ${j + 1}`} className="max-w-full rounded border border-slate-200 dark:border-slate-700 mt-2" />
                        ))}
                        {slide.table && slide.table.length > 0 && (
                          <div className="overflow-x-auto mt-2">
                            <table className="text-xs">
                              <tbody>
                                {slide.table.map((row, ri) => (
                                  <tr key={ri}>
                                    {row.map((cell, ci) => (
                                      <td key={ci} className="px-2 py-1 border border-slate-200 dark:border-slate-600">{String(cell ?? '')}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {officePreview.sheets && (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-500">工作表: {officePreview.sheets.length} 个</p>
                    {officePreview.sheets.map((sheet, i) => {
                      const rows = Array.isArray(sheet.data) ? sheet.data : [];
                      const totalRows = sheet.total_rows || rows.length;
                      return (
                        <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                          <p className="text-xs text-slate-400 mb-1">{sheet.name || `工作表 ${i + 1}`}</p>
                          {rows.length > 0 ? (
                            <div className="overflow-x-auto">
                              <table className="text-xs">
                                <tbody>
                                  {rows.slice(0, 20).map((row, ri) => (
                                    <tr key={ri}>
                                      {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                                        <td key={ci} className="px-2 py-1 border border-slate-200 dark:border-slate-600">{String(cell ?? '')}</td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {totalRows > 20 && <p className="text-xs text-slate-400 mt-1">… 共 {totalRows} 行，仅显示前 20 行</p>}
                            </div>
                          ) : (
                            <p className="text-sm text-slate-400">(无数据)</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* Legacy .doc: interleave extracted images back into the
                    text at their [图片] marker positions. */}
                {officePreview.images?.length > 0 &&
                  (() => {
                    const segments = (officePreview.content || '').split(/(\[图片\])/gi);
                    let imgIdx = 0;
                    const rendered = segments.map((seg, i) => {
                      if (/^\[图片\]$/i.test(seg)) {
                        const src = officePreview.images[imgIdx++];
                        if (src) {
                          return (
                            <img key={i} src={src} alt={`文档插图 ${imgIdx}`} className="max-w-full rounded border border-slate-200 dark:border-slate-700 my-2" />
                          );
                        }
                        return <span key={i}>[图片]</span>;
                      }
                      return seg.trim() ? (
                        <pre key={i} className="text-sm text-slate-800 dark:text-slate-200 whitespace-pre-wrap font-sans">{seg}</pre>
                      ) : null;
                    });
                    // Any images beyond markers still deserve display.
                    for (; imgIdx < officePreview.images.length; imgIdx++) {
                      rendered.push(
                        <img key={`extra-${imgIdx}`} src={officePreview.images[imgIdx]} alt={`文档插图 ${imgIdx + 1}`} className="max-w-full rounded border border-slate-200 dark:border-slate-700 my-2" />
                      );
                    }
                    return <div>{rendered}</div>;
                  })()}
                {officePreview.content && !officePreview.images?.length && !officePreview.slides && !officePreview.sheets && !officePreview.text && (
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
              </>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};

export default OfficePreviewTab;
