// FileListTable.jsx
// "文件列表" tab content: the full file table with selection checkboxes, AI
// analysis cells (summary/keywords/DLL threat badges), expand/collapse detail
// rows, and per-file extract / re-analyze actions.

import Card from '../common/Card';
import Badge from '../common/Badge';
import Button from '../common/Button';
import Spinner from '../common/Spinner';

// DLL / analysis threat-level badge styling (shared between compact & expanded views)
const THREAT_LEVEL_CONFIG = {
  'low': { label: '低风险', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
  'medium': { label: '中风险', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  'high': { label: '高风险', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
  'critical': { label: '严重', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
  '严重': { label: '严重', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
  '高': { label: '高风险', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
  '中': { label: '中风险', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  '低': { label: '低风险', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
};

const getThreatConfig = (level) =>
  THREAT_LEVEL_CONFIG[level] || { label: level, className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' };

const normalizeKeywords = (keywords) =>
  typeof keywords === 'string' ? keywords.split(',') : (keywords || []);

const formatFileSize = (bytes) => {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
};

const FileListTable = ({
  filteredFiles,
  selectAll,
  handleSelectAll,
  selectedFiles,
  handleFileSelect,
  llmAnalyzingFiles,
  dllAnalyzingFiles,
  expandedDescriptions,
  toggleDescription,
  getLLMDescription,
  handleAnalyzeSingleFile,
  openReanalyzeModal,
  llmStatus,
  extractionStatus,
  handleStartExtraction,
  setExtractionMode,
  setExtractionPattern,
}) => {
  const llmUnavailable = llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available';

  return (
    <Card title={`文件列表 (${filteredFiles.length})`}>
      {filteredFiles.length === 0 ? (
        <div className="text-center py-12 text-slate-500 dark:text-slate-400">无文件</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th className="px-3 py-3 w-10">
                  <input
                    type="checkbox"
                    checked={selectAll}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    className="h-4 w-4 text-purple-600 rounded"
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">#</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">名称</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">路径</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">大小</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">扩展名</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">AI 分析</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">操作</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
              {filteredFiles.map((file, index) => {
                const filePath = file.path || file.file_path;
                const fileName = file.name || filePath?.split('/').pop() || '-';
                const llmDesc = getLLMDescription(file);
                const isAnalyzing = llmAnalyzingFiles.has(index);
                const isExpanded = expandedDescriptions.has(filePath);
                const hasDescription = llmDesc && (llmDesc.summary || llmDesc.description);

                return (
                  <>
                    <tr key={index} className={`hover:bg-slate-50 dark:hover:bg-slate-700 ${selectedFiles.has(index) ? 'bg-purple-50 dark:bg-purple-900/20' : ''}`}>
                      <td className="px-3 py-4">
                        <input
                          type="checkbox"
                          checked={selectedFiles.has(index)}
                          onChange={() => handleFileSelect(index)}
                          className="h-4 w-4 text-purple-600 rounded"
                        />
                      </td>
                      <td className="px-4 py-4 text-sm font-medium text-slate-900 dark:text-white">#{index + 1}</td>
                      <td className="px-4 py-4 text-sm font-medium text-slate-900 dark:text-white">
                        {fileName}
                      </td>
                      <td className="px-4 py-4 text-sm text-slate-600 dark:text-slate-300 max-w-xs truncate font-mono" title={filePath}>
                        {filePath || '-'}
                      </td>
                      <td className="px-4 py-4 text-sm text-slate-900 dark:text-white font-mono">
                        {formatFileSize(file.size || file.file_size)}
                      </td>
                      <td className="px-4 py-4 text-sm text-slate-500 dark:text-slate-400">
                        <Badge variant="blue">{file.extension || '-'}</Badge>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-col gap-2">
                          {hasDescription ? (
                            <div className="max-w-md">
                              <div className="flex items-start gap-2">
                                <span className="text-green-500 mt-0.5">✨</span>
                                <div className="flex-1 min-w-0">
                                  {/* DLL Threat Level Badge */}
                                  {llmDesc.isDLLAnalysis && llmDesc.threatLevel && (
                                    <div className="mb-1">
                                      {(() => {
                                        const config = getThreatConfig(llmDesc.threatLevel);
                                        return <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded-full ${config.className}`}>{config.label}</span>;
                                      })()}
                                      {llmDesc.confidence && <span className="ml-1.5 text-xs text-slate-500">置信度: {llmDesc.confidence}%</span>}
                                    </div>
                                  )}
                                  {/* Summary - always visible */}
                                  {llmDesc.summary && (
                                    <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-2 mb-1">
                                      {llmDesc.summary}
                                    </p>
                                  )}

                                  {/* Keywords */}
                                  {llmDesc.keywords && normalizeKeywords(llmDesc.keywords).length > 0 && (
                                    <div className="flex flex-wrap gap-1 mb-1">
                                      {normalizeKeywords(llmDesc.keywords).slice(0, 3).map((kw, i) => (
                                        <span key={i} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                          {kw.trim()}
                                        </span>
                                      ))}
                                      {normalizeKeywords(llmDesc.keywords).length > 3 && (
                                        <span className="text-xs text-slate-500">
                                          +{normalizeKeywords(llmDesc.keywords).length - 3} more
                                        </span>
                                      )}
                                    </div>
                                  )}

                                  {/* Expand/Collapse button for full description */}
                                  {llmDesc.description && (
                                    <button
                                      onClick={() => toggleDescription(filePath)}
                                      className="text-xs text-purple-600 hover:text-purple-800 dark:text-purple-400 dark:hover:text-purple-300"
                                    >
                                      {isExpanded ? '收起详情 ▲' : '展开详情 ▼'}
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                          ) : (
                            /* Analyze Button - only show if no description */
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleAnalyzeSingleFile(file, index)}
                              disabled={isAnalyzing || llmUnavailable}
                              className="text-xs"
                            >
                              {isAnalyzing ? (
                                <>
                                  <Spinner size="sm" />
                                  <span className="ml-2">分析中...</span>
                                </>
                              ) : (
                                '🧠 AI 分析'
                              )}
                            </Button>
                          )}
                          {dllAnalyzingFiles.has(index) && !isAnalyzing && (
                            <div className="analyzing-indicator text-xs text-blue-600 dark:text-blue-400 mt-1">
                              🔍 DLL分析中...
                            </div>
                          )}
                          {/* Re-analyze button - shown when description exists */}
                          {hasDescription && (
                            <button
                              onClick={() => openReanalyzeModal([filePath])}
                              disabled={llmUnavailable}
                              className="text-xs text-amber-600 hover:text-amber-800 dark:text-amber-400 dark:hover:text-amber-300 flex items-center gap-1 mt-1"
                            >
                              🔄 重新分析
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-sm font-medium">
                        <button
                          onClick={() => {
                            setExtractionMode('name');
                            setExtractionPattern(fileName);
                            handleStartExtraction();
                          }}
                          disabled={extractionStatus === 'running'}
                          className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1 p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                          title={`从镜像中提取 ${fileName}`}
                          aria-label={`提取 ${fileName}`}
                        >
                          <span className="text-lg">📥</span>
                          <span>提取</span>
                        </button>
                      </td>
                    </tr>

                    {/* Expanded Full Description Row */}
                    {isExpanded && hasDescription && llmDesc.description && (
                      <tr className="bg-purple-50 dark:bg-purple-900/20">
                        <td colSpan={7} className="px-6 py-4">
                          <div className="space-y-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-lg">📝</span>
                              <h4 className="font-medium text-slate-900 dark:text-white">AI 完整分析</h4>
                            </div>

                            {/* Summary */}
                            {llmDesc.summary && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">摘要</span>
                                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                                  {llmDesc.summary}
                                </p>
                              </div>
                            )}

                            {/* Threat Level & Confidence (DLL analysis) */}
                            {llmDesc.isDLLAnalysis && llmDesc.threatLevel && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">威胁评估</span>
                                <div className="mt-2 flex items-center gap-3">
                                  {(() => {
                                    const config = getThreatConfig(llmDesc.threatLevel);
                                    return (
                                      <>
                                        <span className={`inline-block px-3 py-1 text-sm font-bold rounded-full ${config.className}`}>
                                          {config.label}
                                        </span>
                                        {llmDesc.confidence !== undefined && (
                                          <span className="text-sm text-slate-600 dark:text-slate-300">
                                            置信度: <span className="font-semibold">{llmDesc.confidence}%</span>
                                          </span>
                                        )}
                                      </>
                                    );
                                  })()}
                                </div>
                              </div>
                            )}

                            {/* Suspicious Behaviors (DLL analysis) */}
                            {llmDesc.isDLLAnalysis && llmDesc.suspiciousBehaviors && llmDesc.suspiciousBehaviors.length > 0 && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">可疑行为</span>
                                <ul className="mt-2 space-y-1">
                                  {llmDesc.suspiciousBehaviors.map((behavior, i) => (
                                    <li key={i} className="text-sm text-slate-700 dark:text-slate-300 flex items-start gap-2">
                                      <span className="text-orange-500 mt-1">&#9679;</span>
                                      <span>{behavior}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {/* MITRE ATT&CK Techniques (DLL analysis) */}
                            {llmDesc.isDLLAnalysis && llmDesc.mitreTechniques && llmDesc.mitreTechniques.length > 0 && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">MITRE ATT&amp;CK 技术</span>
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {llmDesc.mitreTechniques.map((tech, i) => (
                                    <span key={i} className="px-2 py-1 text-xs bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 rounded-full font-mono" title={tech.name || tech}>
                                      {typeof tech === 'string' ? tech : (tech.id || tech)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Recommendations (DLL analysis) */}
                            {llmDesc.isDLLAnalysis && llmDesc.recommendations && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">处置建议</span>
                                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                                  {llmDesc.recommendations}
                                </p>
                              </div>
                            )}

                            {/* Full Description */}
                            {llmDesc.description && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">详细描述</span>
                                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                                  {llmDesc.description}
                                </p>
                              </div>
                            )}

                            {/* All Keywords */}
                            {llmDesc.keywords && normalizeKeywords(llmDesc.keywords).length > 0 && (
                              <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">关键词</span>
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {normalizeKeywords(llmDesc.keywords).map((kw, i) => (
                                    <span key={i} className="px-2 py-1 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                      {kw.trim()}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Metadata */}
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                              {llmDesc.model && <span>模型: {llmDesc.model} | </span>}
                              {llmDesc.timestamp && <span>分析时间: {new Date(llmDesc.timestamp).toLocaleString()}</span>}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
};

export default FileListTable;
