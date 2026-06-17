// ClusterInvestigationDrawer.jsx
// Slide-in drawer for investigating a single event cluster: AI analysis panel,
// in-cluster file-path filter, and a virtualised list of the cluster's files.

import { motion, AnimatePresence } from 'framer-motion';
import { Virtuoso } from 'react-virtuoso';
import Badge from '../common/Badge';
import Button from '../common/Button';
import Spinner from '../common/Spinner';
import { X, Brain, RefreshCw, CheckCircle, Search, FileText, Layers } from 'lucide-react';

const formatTimeOnly = (timestamp) => {
    if (!timestamp) return '-';
    return new Date(timestamp * 1000).toLocaleTimeString();
};

const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let i = 0;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return `${size.toFixed(1)} ${units[i]}`;
};

const clusterKey = (c) => `${c.timestamp}-${c.event_type}-${c.parent_directory}`;

const ClusterInvestigationDrawer = ({
    selectedCluster,
    onClose,
    // AI analysis
    onAnalyze,
    onReanalyze,
    analyzingClusters,
    // cluster detail list
    clusterDetails,
    loadingDetails,
    // in-cluster filter
    drawerSearch,
    setDrawerSearch,
}) => {
    return (
        <AnimatePresence>
            {selectedCluster && (
                <>
                    <motion.div
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px] z-40"
                        onClick={onClose}
                    />
                    <motion.div
                        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
                        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                        className="absolute top-0 right-0 bottom-0 w-full lg:w-[550px] bg-white shadow-2xl z-50 border-l border-slate-200 flex flex-col"
                    >
                        <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                            <div>
                                <h3 className="text-sm font-black text-slate-900 uppercase tracking-tighter flex items-center">
                                    <Layers className="w-4 h-4 mr-2 text-primary-500" /> Cluster Investigation
                                </h3>
                                <p className="text-[10px] text-slate-500 font-mono mt-0.5">{selectedCluster.event_type} @ {formatTimeOnly(selectedCluster.timestamp)}</p>
                            </div>
                            <div className="flex items-center space-x-2">
                                {selectedCluster.llm_summary ? (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        icon={RefreshCw}
                                        onClick={() => onReanalyze(selectedCluster)}
                                        disabled={analyzingClusters.has(clusterKey(selectedCluster))}
                                    >
                                        Reanalyze
                                    </Button>
                                ) : (
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        icon={Brain}
                                        onClick={() => onAnalyze(selectedCluster)}
                                        disabled={analyzingClusters.has(clusterKey(selectedCluster))}
                                    >
                                        {analyzingClusters.has(clusterKey(selectedCluster)) ? 'Analyzing...' : 'AI Analyze'}
                                    </Button>
                                )}
                                <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-full transition-colors"><X size={18} /></button>
                            </div>
                        </div>

                        {/* AI Analysis Results */}
                        {selectedCluster.llm_summary && (
                            <div className="px-4 py-3 border-b border-slate-100 bg-primary-50/30">
                                <div className="flex items-start space-x-3">
                                    <div className="flex-shrink-0 mt-1">
                                        <CheckCircle size={16} className="text-green-500" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <h4 className="text-xs font-bold text-slate-700 mb-1">AI Analysis</h4>
                                        <p className="text-[11px] text-slate-600 mb-1.5 whitespace-pre-wrap break-words">{selectedCluster.llm_summary}</p>
                                        {selectedCluster.llm_description && selectedCluster.llm_description !== selectedCluster.llm_summary && (
                                            <details className="mt-2">
                                                <summary className="text-[10px] text-primary-600 cursor-pointer hover:text-primary-700 font-medium">查看详细描述 ▼</summary>
                                                <p className="text-[10px] text-slate-500 mt-1.5 whitespace-pre-wrap break-words pl-2 border-l-2 border-primary-200">{selectedCluster.llm_description}</p>
                                            </details>
                                        )}
                                        {selectedCluster.llm_keywords && (
                                            <div className="flex flex-wrap gap-1">
                                                {selectedCluster.llm_keywords.split(',').map((keyword, idx) => (
                                                    <span key={idx} className="text-[9px] bg-white px-1.5 py-0.5 rounded-full border border-slate-200 text-slate-600">
                                                        {keyword.trim()}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        {selectedCluster.llm_is_relevant && (
                                            <Badge variant="green" className="mt-1.5">Relevant to investigation</Badge>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Drawer Search Bar */}
                        <div className="px-4 py-3 border-b border-slate-100 bg-white sticky top-0 z-10">
                            <div className="relative group">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-primary-500 transition-colors" />
                                <input
                                    type="text"
                                    placeholder="Filter by path in this cluster..."
                                    value={drawerSearch}
                                    onChange={(e) => setDrawerSearch(e.target.value)}
                                    className="w-full pl-9 pr-4 py-2 bg-slate-100/50 border-none rounded-xl text-sm focus:ring-2 focus:ring-primary-500 transition-all"
                                />
                                {drawerSearch && (
                                    <button
                                        onClick={() => setDrawerSearch('')}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-slate-200 rounded-md"
                                    >
                                        <X size={12} className="text-slate-500" />
                                    </button>
                                )}
                            </div>
                        </div>

                        <div className="flex-1 overflow-hidden p-2">
                            {loadingDetails ? (
                                <div className="h-full flex flex-col items-center justify-center">
                                    <Spinner size="lg" />
                                    <span className="text-[10px] mt-4 font-black uppercase tracking-widest text-slate-400">Filtering Cluster...</span>
                                </div>
                            ) : clusterDetails.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 opacity-60">
                                    <Search size={32} strokeWidth={1} />
                                    <p className="text-sm italic">No files match your search.</p>
                                </div>
                            ) : (
                                <Virtuoso
                                    data={clusterDetails}
                                    style={{ height: '100%' }}
                                    itemContent={(index, item) => (
                                        <div key={index} className="px-3 py-2.5 mb-2 bg-white rounded-xl border border-slate-100 hover:border-primary-200 hover:shadow-sm transition-all group">
                                            <div className="flex justify-between items-start gap-4">
                                                <span className="text-[11px] font-bold text-slate-400 font-mono shrink-0 bg-slate-50 px-1.5 py-0.5 rounded">
                                                    {new Date(item.timestamp * 1000).toLocaleTimeString([], { hour12: false, fractionalSecondDigits: 2 })}
                                                </span>
                                                <p className="text-[12px] text-slate-700 font-semibold break-all flex-1 leading-relaxed">{item.file_path}</p>
                                            </div>
                                            <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-400 font-medium">
                                                <span className="bg-slate-50 px-1.5 rounded border border-slate-100">ID:{item.inode}</span>
                                                <span className="flex items-center"><FileText size={10} className="mr-1 opacity-60" /> {formatFileSize(item.file_size)}</span>
                                                {item.file_type && <span className="bg-primary-50 text-primary-600 px-1 rounded font-black uppercase text-[8px]">{item.file_type}</span>}
                                            </div>
                                        </div>
                                    )}
                                />
                            )}
                        </div>
                        <div className="p-3 border-t border-slate-100 bg-slate-50/80 text-[10px] text-slate-500 font-black uppercase flex justify-between tracking-widest">
                            <span>INDEXED: {clusterDetails.length} RESULTS</span>
                            <span className="text-primary-500">Real-time Detail</span>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
};

export default ClusterInvestigationDrawer;
