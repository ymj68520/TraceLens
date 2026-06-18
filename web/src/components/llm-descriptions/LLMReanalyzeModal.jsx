// LLMReanalyzeModal.jsx
// Re-analysis modal for the AI File Descriptions page.

import { motion } from 'framer-motion';
import Spinner from '../common/Spinner';

const LLMReanalyzeModal = ({ show, onClose, targetFiles, hint, setHint, onSubmit, reanalyzing, message }) => {
    if (!show) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
            <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="bg-white dark:bg-slate-800 rounded-3xl shadow-2xl max-w-xl w-full mx-4 overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="p-8">
                    <div className="flex items-center justify-between mb-6">
                        <h3 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
                            <span className="text-2xl">🔄</span> 重新分析选定文件
                        </h3>
                        <button
                            onClick={onClose}
                            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                        >
                            <span className="text-xl">✕</span>
                        </button>
                    </div>

                    <div className="mb-6">
                        <p className="text-sm text-slate-600 dark:text-slate-300">
                            将对 <span className="font-bold text-purple-600">{targetFiles.length}</span> 个文件进行二次深度分析。
                        </p>
                        {targetFiles.length <= 2 && (
                            <div className="mt-2 space-y-1">
                                {targetFiles.map((f, i) => (
                                    <div key={i} className="text-xs font-mono text-slate-400 truncate bg-slate-50 dark:bg-slate-900 p-1.5 rounded">
                                        📄 {f}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="mb-6">
                        <label className="block text-sm font-bold text-slate-700 dark:text-slate-300 mb-2 uppercase tracking-wide">
                            分析指令 / 补充描述
                        </label>
                        <textarea
                            value={hint}
                            onChange={(e) => setHint(e.target.value)}
                            placeholder="请输入对此文件的具体分析方向，例如：关注其中的账户信息、加密货币关键词等..."
                            className="w-full h-36 px-4 py-3 border border-slate-300 dark:border-slate-600 rounded-2xl dark:bg-slate-700 dark:text-white text-sm resize-none focus:ring-4 focus:ring-purple-500/20 focus:border-purple-500 transition-all outline-none"
                            disabled={reanalyzing}
                        />
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-2xl text-sm font-medium animate-pulse ${
                            message.startsWith('✅') ? 'bg-green-50 text-green-800 border border-green-100' :
                            message.startsWith('❌') ? 'bg-red-50 text-red-800 border border-red-100' :
                            'bg-blue-50 text-blue-800 border border-blue-100'
                        }`}>
                            {message}
                        </div>
                    )}

                    <div className="flex justify-end gap-3">
                        <button
                            onClick={onClose}
                            className="px-6 py-2.5 text-sm font-bold text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white transition-colors"
                            disabled={reanalyzing}
                        >
                            取消
                        </button>
                        <button
                            onClick={onSubmit}
                            disabled={reanalyzing || !hint.trim()}
                            className={`px-8 py-2.5 rounded-2xl text-sm font-bold transition-all shadow-lg ${
                                reanalyzing || !hint.trim()
                                    ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 hover:scale-[1.02] active:scale-95'
                            }`}
                        >
                            {reanalyzing ? (
                                <span className="flex items-center gap-2">
                                    <Spinner size="sm" />
                                    执行中...
                                </span>
                            ) : (
                                '🚀 开始重新分析'
                            )}
                        </button>
                    </div>
                </div>
            </motion.div>
        </div>
    );
};

export default LLMReanalyzeModal;
