// ClusterFilesDrawer.jsx
// Slide-in drawer showing the files time-correlated with a selected event cluster.

import { motion, AnimatePresence } from 'framer-motion';
import { Virtuoso } from 'react-virtuoso';
import Spinner from '../common/Spinner';
import { X, FileText, AlertTriangle } from 'lucide-react';

const ClusterFilesDrawer = ({
    selectedClusterForFiles,
    onClose,
    loadingClusterFiles,
    clusterRelatedFiles,
    // anomaly helpers (defined in parent)
    getAnomalyColorClass,
    getAnomalySeverity,
    formatAnomalyType,
}) => (
    <AnimatePresence>
        {selectedClusterForFiles && (
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
                    className="fixed top-0 right-0 bottom-0 w-full lg:w-[600px] bg-white shadow-2xl z-50 border-l border-slate-200 flex flex-col"
                >
                    {/* Header */}
                    <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                        <div>
                            <h3 className="text-sm font-bold text-slate-900">📎 关联文件</h3>
                            <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                                {selectedClusterForFiles.event_type} @ {new Date(selectedClusterForFiles.timestamp * 1000).toLocaleTimeString()}
                            </p>
                        </div>
                        <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-full transition-colors">
                            <X size={18} />
                        </button>
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-hidden">
                        {loadingClusterFiles ? (
                            <div className="h-full flex flex-col items-center justify-center">
                                <Spinner size="lg" />
                                <span className="text-[10px] mt-4 text-slate-400">加载关联文件...</span>
                            </div>
                        ) : clusterRelatedFiles.length === 0 ? (
                            <div className="h-full flex flex-col items-center justify-center text-slate-400">
                                <FileText size={32} strokeWidth={1} />
                                <p className="text-sm mt-2">暂无关联文件</p>
                            </div>
                        ) : (
                            <Virtuoso
                                data={clusterRelatedFiles}
                                style={{ height: '100%' }}
                                itemContent={(index, file) => {
                                    const fileAnomalies = file.anomalies || [];
                                    return (
                                        <div className={`px-4 py-3 border-b border-slate-50 ${fileAnomalies.length > 0 ? 'bg-red-50/30' : ''}`}>
                                            {/* File Path */}
                                            <div className="flex items-start gap-2 mb-2">
                                                <span className="text-lg">📄</span>
                                                <p className="text-[11px] text-slate-700 font-medium break-all flex-1">{file.file_path}</p>
                                            </div>

                                            {/* Time Differences */}
                                            <div className="grid grid-cols-2 gap-2 mb-2">
                                                {file.time_diffs && (
                                                    <>
                                                        {file.time_diffs.mtime_diff !== null && (
                                                            <div className="text-[9px] bg-slate-50 px-2 py-1 rounded">
                                                                <span className="text-slate-500">mtime: </span>
                                                                <span className="font-mono text-slate-700">{file.time_diffs_formatted?.mtime_diff}</span>
                                                            </div>
                                                        )}
                                                        {file.time_diffs.ctime_diff !== null && (
                                                            <div className="text-[9px] bg-slate-50 px-2 py-1 rounded">
                                                                <span className="text-slate-500">ctime: </span>
                                                                <span className="font-mono text-slate-700">{file.time_diffs_formatted?.ctime_diff}</span>
                                                            </div>
                                                        )}
                                                    </>
                                                )}
                                            </div>

                                            {/* Anomalies */}
                                            {fileAnomalies.length > 0 && (
                                                <div className="flex flex-wrap gap-1 mt-2">
                                                    {fileAnomalies.map((anomaly, idx) => (
                                                        <span
                                                            key={idx}
                                                            className={`text-[9px] px-2 py-0.5 rounded-full border font-medium ${getAnomalyColorClass(getAnomalySeverity(anomaly))}`}
                                                        >
                                                            <AlertTriangle size={10} className="inline mr-1" />
                                                            {formatAnomalyType(anomaly)}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}

                                            {/* File Summary if available */}
                                            {file.llm_summary && (
                                                <p className="text-[10px] text-slate-500 mt-2 line-clamp-2">{file.llm_summary}</p>
                                            )}
                                        </div>
                                    );
                                }}
                            />
                        )}
                    </div>

                    {/* Footer */}
                    <div className="p-3 border-t border-slate-100 bg-slate-50/80 text-[10px] text-slate-500 flex justify-between">
                        <span>共 {clusterRelatedFiles.length} 个关联文件</span>
                        <span className="text-purple-500 font-medium">时间关联分析</span>
                    </div>
                </motion.div>
            </>
        )}
    </AnimatePresence>
);

export default ClusterFilesDrawer;
