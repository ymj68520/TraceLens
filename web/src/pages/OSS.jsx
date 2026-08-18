import { motion } from 'framer-motion';
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import {
    startAnalysis,
    pollAnalysisStatus,
    getObjects,
    getAccessLogs,
    getSummary,
    getStorageClassStats,
    getExtensionStats,
    getBuckets,
} from '../services/ossService';

export default function OSS() {
    const [searchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');
    const { tasks } = useSelector((state) => state.tasks);
    const currentTask = tasks.find((t) => t.id === taskId);

    const [activeTab, setActiveTab] = useState('summary');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Analysis state
    const [analyzing, setAnalyzing] = useState(false);
    const [analysisProgress, setAnalysisProgress] = useState(null);
    const [sourcePath, setSourcePath] = useState('');

    // Data states
    const [summary, setSummary] = useState(null);
    const [objects, setObjects] = useState([]);
    const [accessLogs, setAccessLogs] = useState([]);
    const [buckets, setBuckets] = useState([]);
    const [storageStats, setStorageStats] = useState(null);
    const [extensionStats, setExtensionStats] = useState(null);

    // Load data based on active tab
    const loadTabData = useCallback(async () => {
        if (!taskId) return;
        setLoading(true);
        setError(null);
        try {
            switch (activeTab) {
                case 'summary': {
                    const [summaryData, storageData, extData] = await Promise.all([
                        getSummary(taskId).catch(() => null),
                        getStorageClassStats(taskId).catch(() => null),
                        getExtensionStats(taskId).catch(() => null),
                    ]);
                    setSummary(summaryData);
                    setStorageStats(storageData);
                    setExtensionStats(extData);
                    break;
                }
                case 'objects': {
                    const data = await getObjects(taskId, { limit: 100 });
                    setObjects(data.objects || data.data || []);
                    break;
                }
                case 'logs': {
                    const data = await getAccessLogs(taskId, { limit: 100 });
                    setAccessLogs(data.logs || data.data || []);
                    break;
                }
                case 'buckets': {
                    const data = await getBuckets(taskId);
                    setBuckets(data.buckets || data.data || []);
                    break;
                }
            }
        } catch (err) {
            setError(err.message || 'Failed to load data');
        } finally {
            setLoading(false);
        }
    }, [taskId, activeTab]);

    useEffect(() => {
        loadTabData();
    }, [loadTabData]);

    // Start OSS analysis
    const handleStartAnalysis = async () => {
        if (!taskId) return;
        setAnalyzing(true);
        setAnalysisProgress(null);
        try {
            const result = await startAnalysis(taskId, { sourcePath });
            if (result.job_id) {
                await pollAnalysisStatus(result.job_id, (status) => {
                    setAnalysisProgress(status);
                });
                loadTabData();
            }
        } catch (err) {
            setError('Analysis failed: ' + (err.message || 'Unknown error'));
        } finally {
            setAnalyzing(false);
        }
    };

    const formatSize = (bytes) => {
        if (!bytes) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = bytes, idx = 0;
        while (size >= 1024 && idx < units.length - 1) { size /= 1024; idx++; }
        return `${size.toFixed(1)} ${units[idx]}`;
    };

    const formatDate = (dateStr) => {
        if (!dateStr) return '-';
        try { return new Date(dateStr).toLocaleString(); } catch { return dateStr; }
    };

    const tabs = [
        { id: 'summary', label: '📊 概览' },
        { id: 'objects', label: '📦 对象' },
        { id: 'logs', label: '📜 访问日志' },
        { id: 'buckets', label: '🪣 Buckets' },
    ];

    if (!taskId) {
        return (
            <div className="space-y-6">
                <div>
                    <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">OSS 对象存储分析</motion.h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-300">对象存储取证分析</p>
                </div>
                <Card title="选择任务">
                    <p className="text-slate-500 dark:text-slate-400">
                        请从 <a href="/tasks" className="text-primary-600 hover:text-blue-800 dark:text-primary-400">任务页面</a> 选择一个已完成的任务。
                    </p>
                </Card>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">OSS 对象存储分析</motion.h1>
                <p className="mt-2 text-slate-600 dark:text-slate-300">
                    任务: {currentTask?.image_path || taskId}
                </p>
            </div>

            {/* Analysis Control */}
            <Card title="🚀 启动 OSS 分析" className="bg-indigo-50 dark:bg-indigo-900/10 border-indigo-200 dark:border-indigo-800">
                <div className="space-y-4">
                    <div className="flex gap-4 items-end">
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">数据源路径</label>
                            <input
                                type="text"
                                value={sourcePath}
                                onChange={(e) => setSourcePath(e.target.value)}
                                placeholder="/path/to/oss/export 或 OSS 配置文件路径"
                                disabled={analyzing}
                                className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
                            />
                        </div>
                        <Button onClick={handleStartAnalysis} disabled={analyzing}>
                            {analyzing ? <><Spinner size="sm" className="mr-2" />分析中...</> : '开始分析'}
                        </Button>
                    </div>
                    {analysisProgress && (
                        <div className="p-3 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
                            <div className="flex justify-between text-sm mb-1">
                                <span className="text-slate-600 dark:text-slate-300">
                                    已分析 {analysisProgress.objects_analyzed || 0} 对象, {analysisProgress.logs_analyzed || 0} 日志
                                </span>
                                <Badge variant={analysisProgress.status === 'COMPLETED' ? 'green' : 'blue'}>
                                    {analysisProgress.status}
                                </Badge>
                            </div>
                        </div>
                    )}
                </div>
            </Card>

            {error && (
                <div className="p-4 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded-xl">
                    {error}
                    <button onClick={() => setError(null)} className="ml-4 text-sm underline">关闭</button>
                </div>
            )}

            {/* Tabs */}
            <div className="border-b border-slate-200 dark:border-slate-700">
                <nav className="-mb-px flex space-x-8">
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`${activeTab === tab.id
                                ? 'border-blue-500 text-primary-600 dark:text-primary-400'
                                : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400'
                                } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </nav>
            </div>

            {loading ? (
                <Card>
                    <div className="flex items-center justify-center h-48">
                        <Spinner size="lg" />
                        <span className="ml-4 text-slate-600 dark:text-slate-300">加载中...</span>
                    </div>
                </Card>
            ) : (
                <>
                    {/* Summary Tab */}
                    {activeTab === 'summary' && (
                        <div className="space-y-6">
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                                {[
                                    { label: '总对象数', value: summary?.total_objects || 0, icon: '📦', color: 'blue' },
                                    { label: '总大小', value: formatSize(summary?.total_size || 0), icon: '💾', color: 'green' },
                                    { label: '日志条数', value: summary?.total_logs || 0, icon: '📜', color: 'purple' },
                                    { label: 'Buckets', value: summary?.total_buckets || 0, icon: '🪣', color: 'orange' },
                                ].map((stat) => (
                                    <Card key={stat.label} className="hover:shadow-md transition-shadow">
                                        <div className="flex items-center">
                                            <div className="text-3xl mr-4">{stat.icon}</div>
                                            <div>
                                                <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{stat.label}</p>
                                                <p className="text-2xl font-bold text-slate-900 dark:text-white">{stat.value}</p>
                                            </div>
                                        </div>
                                    </Card>
                                ))}
                            </div>

                            {/* Storage Class Stats */}
                            {storageStats && (
                                <Card title="存储类型分布">
                                    <div className="space-y-3">
                                        {(storageStats.statistics || []).map((s, i) => (
                                            <div key={i} className="flex items-center justify-between">
                                                <span className="text-sm text-slate-700 dark:text-slate-300">{s.storage_class || 'Standard'}</span>
                                                <div className="flex items-center gap-4">
                                                    <span className="text-sm font-medium">{s.count || 0} 对象</span>
                                                    <span className="text-sm text-slate-500">{formatSize(s.total_size || 0)}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </Card>
                            )}

                            {/* Extension Stats */}
                            {extensionStats && (
                                <Card title="文件扩展名分布">
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                                        {(extensionStats.statistics || []).slice(0, 12).map((s, i) => (
                                            <div key={i} className="flex justify-between items-center px-3 py-2 bg-slate-50 dark:bg-slate-800 rounded">
                                                <Badge variant="blue">{s.extension || 'N/A'}</Badge>
                                                <span className="text-sm font-medium">{s.count || 0}</span>
                                            </div>
                                        ))}
                                    </div>
                                </Card>
                            )}
                        </div>
                    )}

                    {/* Objects Tab */}
                    {activeTab === 'objects' && (
                        <Card title={`对象列表 (${objects.length})`}>
                            {objects.length === 0 ? (
                                <div className="text-center py-12 text-slate-500 dark:text-slate-400">暂无对象数据</div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                                        <thead className="bg-slate-50 dark:bg-slate-800">
                                            <tr>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">Key</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">大小</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">存储类型</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">修改时间</th>
                                            </tr>
                                        </thead>
                                        <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                                            {objects.map((obj, i) => (
                                                <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-700">
                                                    <td className="px-4 py-3 text-sm font-mono text-slate-900 dark:text-white max-w-xs truncate" title={obj.key}>{obj.key || obj.name || '-'}</td>
                                                    <td className="px-4 py-3 text-sm text-slate-900 dark:text-white font-mono">{formatSize(obj.size)}</td>
                                                    <td className="px-4 py-3"><Badge variant="blue">{obj.storage_class || 'Standard'}</Badge></td>
                                                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">{formatDate(obj.last_modified)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </Card>
                    )}

                    {/* Logs Tab */}
                    {activeTab === 'logs' && (
                        <Card title={`访问日志 (${accessLogs.length})`}>
                            {accessLogs.length === 0 ? (
                                <div className="text-center py-12 text-slate-500 dark:text-slate-400">暂无日志数据</div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                                        <thead className="bg-slate-50 dark:bg-slate-800">
                                            <tr>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">时间</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">操作</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">Key</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">IP</th>
                                                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">状态</th>
                                            </tr>
                                        </thead>
                                        <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                                            {accessLogs.map((log, i) => (
                                                <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-700">
                                                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">{formatDate(log.timestamp || log.time)}</td>
                                                    <td className="px-4 py-3"><Badge variant={log.operation === 'GET' ? 'green' : log.operation === 'DELETE' ? 'red' : 'blue'}>{log.operation || '-'}</Badge></td>
                                                    <td className="px-4 py-3 text-sm font-mono text-slate-900 dark:text-white max-w-xs truncate">{log.key || '-'}</td>
                                                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400 font-mono">{log.remote_ip || log.ip || '-'}</td>
                                                    <td className="px-4 py-3 text-sm">{log.http_status || log.status || '-'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </Card>
                    )}

                    {/* Buckets Tab */}
                    {activeTab === 'buckets' && (
                        <Card title={`Buckets (${buckets.length})`}>
                            {buckets.length === 0 ? (
                                <div className="text-center py-12 text-slate-500 dark:text-slate-400">暂无 Bucket 数据</div>
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {buckets.map((bucket, i) => (
                                        <Card key={i} className="hover:shadow-md transition-shadow">
                                            <div className="space-y-2">
                                                <h3 className="font-medium text-slate-900 dark:text-white text-lg">🪣 {bucket.name || 'Unknown'}</h3>
                                                <div className="grid grid-cols-2 gap-2 text-sm">
                                                    <span className="text-slate-500">区域:</span>
                                                    <span className="text-slate-900 dark:text-white">{bucket.region || '-'}</span>
                                                    <span className="text-slate-500">创建时间:</span>
                                                    <span className="text-slate-900 dark:text-white">{formatDate(bucket.creation_date)}</span>
                                                    <span className="text-slate-500">对象数:</span>
                                                    <span className="font-medium">{bucket.object_count || 0}</span>
                                                    <span className="text-slate-500">总大小:</span>
                                                    <span className="font-medium">{formatSize(bucket.total_size || 0)}</span>
                                                </div>
                                            </div>
                                        </Card>
                                    ))}
                                </div>
                            )}
                        </Card>
                    )}
                </>
            )}
        </div>
    );
}
