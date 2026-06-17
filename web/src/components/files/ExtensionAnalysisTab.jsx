// ExtensionAnalysisTab.jsx
// "按扩展名分布" tab content: table of file extensions with counts/sizes/percentages.

import Card from '../common/Card';
import Badge from '../common/Badge';

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

const ExtensionAnalysisTab = ({ extensionAnalysis }) => {
  if (!extensionAnalysis) return null;

  const hasData = extensionAnalysis.extension_analysis && extensionAnalysis.extension_analysis.length > 0;
  const totalCount =
    extensionAnalysis.total_count ||
    extensionAnalysis.extension_analysis.reduce((sum, e) => sum + (e.file_count || 0), 0);

  return (
    <Card title="按扩展名分布">
      {hasData ? (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">扩展名</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">数量</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">总大小</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">占比</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
              {extensionAnalysis.extension_analysis
                .sort((a, b) => (b.file_count || 0) - (a.file_count || 0))
                .map((ext, index) => {
                  const percentage = totalCount > 0 ? ((ext.file_count || 0) / totalCount * 100).toFixed(1) : '0.0';
                  return (
                    <tr key={index} className="hover:bg-slate-50 dark:hover:bg-slate-700">
                      <td className="px-6 py-4">
                        <Badge variant="blue">{ext.extension || '(无扩展名)'}</Badge>
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">{ext.file_count || 0}</td>
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white font-mono">{formatFileSize(ext.total_size || 0)}</td>
                      <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">{percentage}%</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-slate-500 dark:text-slate-400">无扩展名数据</div>
      )}
    </Card>
  );
};

export default ExtensionAnalysisTab;
