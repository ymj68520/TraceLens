// ExtractionControls.jsx
// Right column of the control console: data extraction controls and AI/KG action
// buttons (batch analysis, re-analysis, graphiti ingest) with progress indicators.

import Button from '../common/Button';
import Spinner from '../common/Spinner';

const ExtractionControls = ({
  // Extraction
  setExtractionMode,
  setExtractionPattern,
  includeDeleted,
  setIncludeDeleted,
  overwrite,
  setOverwrite,
  extractionStatus,
  extractionProgress,
  extractionMessage,
  handleStartExtraction,
  // AI / KG
  llmStatus,
  isBatchRunning,
  activeBatch,
  graphitiStatus,
  graphitiIngesting,
  graphitiMessage,
  handleBatchAnalyze,
  handleGraphitiIngest,
  openReanalyzeModal,
  // Selection (for extract-selected / re-analyze selected)
  selectedFiles,
  filteredFiles,
}) => {
  const llmUnavailable = llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available';

  return (
    <div className="lg:col-span-8 space-y-6">
      {/* Row 1: Extract Controls */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">📁 数据提取</h4>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
              <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} disabled={extractionStatus === 'running'} className="rounded text-primary-600 h-3.5 w-3.5" />
              覆盖
            </label>
            <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
              <input type="checkbox" checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} disabled={extractionStatus === 'running'} className="rounded text-primary-600 h-3.5 w-3.5" />
              含已删除
            </label>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" onClick={handleStartExtraction} disabled={extractionStatus === 'running'}>
            {extractionStatus === 'running' ? <Spinner size="sm" /> : '🚀 提取所有匹配'}
          </Button>
          <Button variant="outline" size="sm" onClick={async () => {
            const names = [...selectedFiles].map(idx => filteredFiles[idx].name || (filteredFiles[idx].path || filteredFiles[idx].file_path)?.split('/').pop()).filter(Boolean);
            if (names.length > 0) { setExtractionMode('name'); setExtractionPattern(names.join(',')); handleStartExtraction(); }
          }} disabled={selectedFiles.size === 0 || extractionStatus === 'running'}>
            📥 提取选中 ({selectedFiles.size})
          </Button>
          {extractionStatus !== 'idle' && (
            <div className="flex-1 flex items-center gap-3 px-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg min-w-[200px]">
              <div className="flex-1 h-1.5 bg-blue-200 dark:bg-blue-800 rounded-full overflow-hidden">
                <div className="bg-blue-600 h-full transition-all" style={{ width: `${extractionProgress}%` }} />
              </div>
              <span className="text-[10px] font-mono text-blue-700 dark:text-blue-300 whitespace-nowrap">{extractionMessage}</span>
            </div>
          )}
        </div>
      </div>

      {/* Row 2: AI & KG Actions */}
      <div className="space-y-3 pt-4 border-t border-slate-100 dark:border-slate-700">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">🧠 AI 取证 &amp; 建模</h4>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={handleBatchAnalyze}
            disabled={isBatchRunning || llmUnavailable}
            className="bg-purple-600 hover:bg-purple-700 text-white"
            title={selectedFiles.size > 0 ? `将分析选中的 ${selectedFiles.size} 个文件` : `将分析当前筛选结果中的所有文件`}
          >
            {isBatchRunning ? <Spinner size="sm" /> : '🧠 批量分析'}
            {selectedFiles.size > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-white/20 rounded">
                {selectedFiles.size}
              </span>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const paths = [...selectedFiles].map(idx => filteredFiles[idx].path || filteredFiles[idx].file_path).filter(Boolean);
              if (paths.length > 0) openReanalyzeModal(paths);
            }}
            disabled={selectedFiles.size === 0 || llmUnavailable}
          >
            🔄 批量重新分析
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleGraphitiIngest}
            disabled={graphitiIngesting || !graphitiStatus?.neo4j_connected}
          >
            {graphitiIngesting ? <Spinner size="sm" /> : '🕸️ 导入图谱'}
          </Button>

          {/* AI Progress */}
          {(isBatchRunning || graphitiIngesting || graphitiMessage) && (
            <div className="flex-1 flex items-center gap-3 px-3 bg-purple-50 dark:bg-purple-900/20 rounded-lg min-w-[200px]">
              {isBatchRunning && (
                <>
                  <div className="flex-1 h-1.5 bg-purple-200 dark:bg-purple-800 rounded-full overflow-hidden">
                    <div className="bg-purple-600 h-full transition-all" style={{ width: `${activeBatch?.progress || 0}%` }} />
                  </div>
                  <span className="text-[10px] font-mono text-purple-700 dark:text-purple-300 whitespace-nowrap">{activeBatch?.message || ""}</span>
                </>
              )}
              {!isBatchRunning && graphitiMessage && (
                <span className="text-xs text-purple-700 dark:text-purple-300 truncate">
                  {graphitiIngesting && <Spinner size="sm" className="mr-2" />}
                  {graphitiMessage}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ExtractionControls;
