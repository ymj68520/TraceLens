// ReanalyzeModal.jsx
// Modal dialog for re-analyzing one or more files with an extra hint.

import Spinner from '../common/Spinner';

const ReanalyzeModal = ({ show, onClose, targetFiles, hint, setHint, onSubmit, reanalyzing, message }) => {
  if (!show) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-lg w-full mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            🔄 重新分析文件
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            ✕
          </button>
        </div>

        <div className="mb-4">
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            将对 <span className="font-bold text-purple-600">{targetFiles.length}</span> 个文件进行二次分析，结合案情描述和知识图谱上下文。
          </p>
          {targetFiles.length <= 3 && (
            <div className="space-y-1 mb-3">
              {targetFiles.map((f, i) => (
                <div key={i} className="text-xs font-mono text-slate-500 dark:text-slate-400 truncate">
                  📄 {f}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            补充描述 / 分析提示
          </label>
          <textarea
            value={hint}
            onChange={(e) => setHint(e.target.value)}
            placeholder="请输入对该文件的额外描述或分析方向，例如：请重点关注转账记录和可疑联系人..."
            className="w-full h-28 px-4 py-3 border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white text-sm resize-none focus:ring-2 focus:ring-purple-500"
            disabled={reanalyzing}
          />
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-xl text-sm ${message.startsWith('✅') ? 'bg-green-50 text-green-800 dark:bg-green-900/30 dark:text-green-200' :
            message.startsWith('❌') ? 'bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200' :
              'bg-blue-50 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200'
            }`}>
            {message}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl"
            disabled={reanalyzing}
          >
            取消
          </button>
          <button
            onClick={onSubmit}
            disabled={reanalyzing || !hint.trim()}
            className={`px-6 py-2 rounded-xl text-sm font-medium transition-all ${reanalyzing || !hint.trim()
              ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
              : 'bg-gradient-to-r from-amber-500 to-orange-500 text-white hover:from-amber-600 hover:to-orange-600 shadow-lg'
              }`}
          >
            {reanalyzing ? (
              <span className="flex items-center">
                <Spinner size="sm" />
                <span className="ml-2">分析中...</span>
              </span>
            ) : (
              '🔄 开始重新分析'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReanalyzeModal;
