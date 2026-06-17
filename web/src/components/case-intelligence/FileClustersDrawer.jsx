// FileClustersDrawer.jsx
// Slide-in drawer showing the event clusters time-correlated with a selected file.

import { motion, AnimatePresence } from 'framer-motion';
import { Virtuoso } from 'react-virtuoso';
import Badge from '../common/Badge';
import Spinner from '../common/Spinner';
import { X, Clock } from 'lucide-react';

const FileClustersDrawer = ({
    selectedFileForClusters,
    onClose,
    loadingFileClusters,
    fileRelatedClusters,
    activeContextId,
    navigate,
}) => (
    <AnimatePresence>
        {selectedFileForClusters && (
            <>
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 bg-slate-900/20 backdrop-blur-sm z-40"
                    onClick={onClose}
                />
                <motion.div
                    initial={{ x: '100%' }}
                    animate={{ x: 0 }}
                    exit={{ x: '100%' }}
                    transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                    className="fixed top-0 right-0 bottom-0 w-full lg:w-[500px] bg-white shadow-2xl z-50 border-l border-slate-200 flex flex-col"
                >
                    {/* Header */}
                    <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                        <div>
                            <h3 className="text-sm font-bold text-slate-900">🔗 关联事件簇</h3>
                            <p className="text-[10px] text-slate-500 font-mono mt-0.5 max-w-[300px] truncate">
                                {selectedFileForClusters.file_path}
                            </p>
                        </div>
                        <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-full transition-colors">
                            <X size={18} />
                        </button>
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-hidden">
                        {loadingFileClusters ? (
                            <div className="h-full flex flex-col items-center justify-center">
                                <Spinner size="lg" />
                                <span className="text-[10px] mt-4 text-slate-400">加载关联事件簇...</span>
                            </div>
                        ) : fileRelatedClusters.length === 0 ? (
                            <div className="h-full flex flex-col items-center justify-center text-slate-400">
                                <Clock size={32} strokeWidth={1} />
                                <p className="text-sm mt-2">暂无关联事件簇</p>
                            </div>
                        ) : (
                            <Virtuoso
                                data={fileRelatedClusters}
                                style={{ height: '100%' }}
                                itemContent={(index, cluster) => (
                                    <div className="px-4 py-3 border-b border-slate-50 hover:bg-slate-50 transition-colors">
                                        {/* Event Type Badge */}
                                        <div className="flex items-center gap-2 mb-2">
                                            <Badge variant={
                                                cluster.event_type === 'CREATED' ? 'green' :
                                                cluster.event_type === 'MODIFIED' ? 'blue' :
                                                cluster.event_type === 'DELETED' ? 'red' : 'gray'
                                            } className="text-[9px] px-2 py-0.5 font-bold">
                                                {cluster.event_type}
                                            </Badge>
                                            <span className="text-[10px] text-slate-500">
                                                {new Date(cluster.representative_timestamp * 1000).toLocaleString()}
                                            </span>
                                        </div>

                                        {/* Directory */}
                                        <p className="text-[10px] text-slate-600 font-mono mb-1 truncate">
                                            📁 {cluster.parent_directory || '/'}
                                        </p>

                                        {/* Match Info */}
                                        {cluster.matched_time && (
                                            <div className="text-[9px] bg-purple-50 px-2 py-1 rounded mb-1">
                                                <span className="text-purple-700">匹配时间: {cluster.matched_time} </span>
                                                <span className="text-purple-500 font-mono">({cluster.time_diff_formatted})</span>
                                            </div>
                                        )}

                                        {/* Event Count */}
                                        <div className="text-[9px] text-slate-500">
                                            包含 {cluster.cluster_count || cluster.event_count} 个事件
                                        </div>

                                        {/* AI Summary */}
                                        {cluster.llm_summary && (
                                            <p className="text-[10px] text-slate-600 mt-2 line-clamp-2">{cluster.llm_summary}</p>
                                        )}

                                        {/* Action Button */}
                                        <button
                                            onClick={() => {
                                                onClose();
                                                navigate(`/timeline?task_id=${activeContextId}&type=${cluster.event_type}&cluster=true`);
                                            }}
                                            className="mt-2 text-[9px] text-blue-500 hover:text-blue-700 font-medium"
                                        >
                                            在时间线中查看 →
                                        </button>
                                    </div>
                                )}
                            />
                        )}
                    </div>

                    {/* Footer */}
                    <div className="p-3 border-t border-slate-100 bg-slate-50/80 text-[10px] text-slate-500 flex justify-between">
                        <span>共 {fileRelatedClusters.length} 个关联事件簇</span>
                        <span className="text-blue-500 font-medium">时间关联分析</span>
                    </div>
                </motion.div>
            </>
        )}
    </AnimatePresence>
);

export default FileClustersDrawer;
