import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Virtuoso } from 'react-virtuoso';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { useTranslation } from '../hooks/useTranslation';
import { getComprehensiveTimeline, getTimelineDistribution, getTimelineDetails, analyzeEventCluster, reanalyzeEventCluster } from '../services/forensicsService';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Calendar, Filter, X, ChevronLeft, ChevronRight, FileText, Clock, Layers, Folder, ArrowRight, Search, Brain, RefreshCw, CheckCircle2 } from 'lucide-react';

// --- Helper Functions ---
const formatTimestamp = (timestamp) => {
  if (!timestamp) return '-';
  return new Date(timestamp * 1000).toLocaleString();
};

const formatTimeOnly = (timestamp) => {
  if (!timestamp) return '-';
  return new Date(timestamp * 1000).toLocaleTimeString();
};

const formatFileSize = (bytes) => {
  const size = parseFloat(bytes);
  if (isNaN(size) || size <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let unitIndex = 0;
  let displaySize = size;
  while (displaySize >= 1024 && unitIndex < units.length - 1) {
    displaySize /= 1024;
    unitIndex++;
  }
  return `${displaySize.toFixed(1)} ${units[unitIndex]}`;
};

const Timeline = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);
  const { itemsPerPage } = useSelector((state) => state.settings);

  const currentPage = parseInt(searchParams.get('page')) || 1;
  const pageSize = itemsPerPage || 50;
  const eventType = searchParams.get('type') || '';
  const selectedDate = searchParams.get('date') || '';
  const isClustered = searchParams.get('cluster') !== 'false';
  const viewMode = searchParams.get('view') || 'timeline';

  const [timelineData, setTimelineData] = useState(null);
  const [distributionData, setDistributionData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Investigation Drawer State
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [clusterDetails, setClusterDetails] = useState([]);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [drawerSearch, setDrawerSearch] = useState('');
  
  // AI Analysis State
  const [analyzingClusters, setAnalyzingClusters] = useState(new Set());
  const [analyzedClusters, setAnalyzedClusters] = useState(new Set());

  const virtuosoRef = useRef();
  const currentTask = tasks.find((t) => t.id === taskId);

  const updateParams = useCallback((newParams) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(newParams).forEach(([key, value]) => {
      if (value === undefined || value === '' || value === null) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  const fetchTimeline = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);

    try {
      const offset = (currentPage - 1) * pageSize;
      const params = {
        limit: pageSize,
        offset: offset,
        event_type: eventType || undefined,
        cluster: isClustered
      };

      console.log('Fetching timeline with params:', params);

      if (selectedDate) {
        const start = Math.floor(new Date(selectedDate).getTime() / 1000);
        params.start_time = start.toString();
        params.end_time = (start + 86400).toString();
      }

      console.log('Final params:', params);
      const data = await getComprehensiveTimeline(taskId, params);
      console.log('Received timeline data:', data);
      setTimelineData(data);
      if (virtuosoRef.current) virtuosoRef.current.scrollToIndex({ index: 0 });
    } catch (err) {
      console.error('Failed to fetch timeline:', err);
      setError(err.message || 'Failed to load timeline data');
    } finally {
      setLoading(false);
    }
  }, [taskId, currentPage, pageSize, eventType, selectedDate, isClustered]);

  useEffect(() => {
    if (taskId) {
        getTimelineDistribution(taskId).then(timelineDist => {
            if (timelineDist && timelineDist.distribution) {
                const distMap = {};
                timelineDist.distribution.forEach(item => {
                  if (!distMap[item.event_date]) distMap[item.event_date] = { date: item.event_date, CREATED: 0, MODIFIED: 0, DELETED: 0, OTHER: 0 };
                  const type = ['CREATED', 'MODIFIED', 'DELETED'].includes(item.event_type) ? item.event_type : 'OTHER';
                  distMap[item.event_date][type] += item.count;
                });
                setDistributionData(Object.values(distMap).sort((a,b) => a.date.localeCompare(b.date)));
            }
        }).catch(err => console.error('Dist error', err));
    }
  }, [taskId]);

  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);

  // Cluster Detail Fetching with Search Support
  const fetchClusterDetails = useCallback(async (cluster, search) => {
    if (!cluster) return;
    setLoadingDetails(true);
    try {
        const window = Math.floor(cluster.timestamp / 60);
        const data = await getTimelineDetails(taskId, {
            window,
            type: cluster.event_type,
            dir: cluster.parent_directory,
            search: search || undefined,
            limit: 5000 
        });
        setClusterDetails(data.events || []);
    } catch (err) {
        console.error('Failed to fetch cluster details', err);
    } finally {
        setLoadingDetails(false);
    }
  }, [taskId]);

  // Handle Initial Open
  const handleOpenCluster = (event) => {
    setSelectedCluster(event);
    setDrawerSearch('');
    fetchClusterDetails(event, '');
  };

  // Debounced search for Drawer
  useEffect(() => {
    if (!selectedCluster) return;
    const timer = setTimeout(() => {
        fetchClusterDetails(selectedCluster, drawerSearch);
    }, 350);
    return () => clearTimeout(timer);
  }, [drawerSearch, selectedCluster, fetchClusterDetails]);
  
  // Handle AI Analysis for Event Clusters
  const handleAnalyzeCluster = async (cluster) => {
    const clusterKey = `${cluster.timestamp}-${cluster.event_type}-${cluster.parent_directory}`;
    setAnalyzingClusters(prev => new Set(prev).add(clusterKey));
    
    try {
      await analyzeEventCluster(taskId, cluster);
      setAnalyzedClusters(prev => new Set(prev).add(clusterKey));
      // Refresh timeline data to show AI analysis results
      fetchTimeline();
    } catch (error) {
      console.error('Failed to analyze event cluster:', error);
    } finally {
      setAnalyzingClusters(prev => {
        const newSet = new Set(prev);
        newSet.delete(clusterKey);
        return newSet;
      });
    }
  };
  
  const handleReanalyzeCluster = async (cluster) => {
    const clusterKey = `${cluster.timestamp}-${cluster.event_type}-${cluster.parent_directory}`;
    setAnalyzingClusters(prev => new Set(prev).add(clusterKey));
    
    try {
      await reanalyzeEventCluster(taskId, cluster);
      // Refresh timeline data to show updated AI analysis results
      fetchTimeline();
    } catch (error) {
      console.error('Failed to reanalyze event cluster:', error);
    } finally {
      setAnalyzingClusters(prev => {
        const newSet = new Set(prev);
        newSet.delete(clusterKey);
        return newSet;
      });
    }
  };

  const handleBarClick = (data) => {
    if (data && data.activePayload && data.activePayload[0]) {
      const date = data.activePayload[0].payload.date;
      updateParams({ date: date === selectedDate ? '' : date, page: 1 });
    }
  };

  const resetFilters = () => {
    updateParams({ type: '', date: '', page: 1, cluster: 'true' });
  };

  const events = useMemo(() => {
    console.log('Timeline data:', timelineData);
    return timelineData?.timeline || [];
  }, [timelineData]);
  const metadata = timelineData?.metadata || {};
  const totalCount = metadata.total_events || 0;
  const totalPages = Math.ceil(totalCount / pageSize);

  if (!taskId) return <div className="p-8 text-center text-slate-500">Please select a task...</div>;

  return (
    <div className="h-[calc(100vh-140px)] flex flex-col space-y-4 overflow-hidden relative">
      {/* Investigation Drawer */}
      <AnimatePresence>
        {selectedCluster && (
          <>
            <motion.div 
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px] z-40"
              onClick={() => setSelectedCluster(null)}
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
                      onClick={() => handleReanalyzeCluster(selectedCluster)}
                      disabled={analyzingClusters.has(`${selectedCluster.timestamp}-${selectedCluster.event_type}-${selectedCluster.parent_directory}`)}
                    >
                      Reanalyze
                    </Button>
                  ) : (
                    <Button 
                      variant="primary" 
                      size="sm" 
                      icon={Brain} 
                      onClick={() => handleAnalyzeCluster(selectedCluster)}
                      disabled={analyzingClusters.has(`${selectedCluster.timestamp}-${selectedCluster.event_type}-${selectedCluster.parent_directory}`)}
                    >
                      {analyzingClusters.has(`${selectedCluster.timestamp}-${selectedCluster.event_type}-${selectedCluster.parent_directory}`) ? 'Analyzing...' : 'AI Analyze'}
                    </Button>
                  )}
                  <button onClick={() => setSelectedCluster(null)} className="p-2 hover:bg-slate-100 rounded-full transition-colors"><X size={18} /></button>
                </div>
              </div>
              
              {/* AI Analysis Results */}
              {selectedCluster.llm_summary && (
                <div className="px-4 py-3 border-b border-slate-100 bg-primary-50/30">
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 mt-1">
                      <CheckCircle2 size={16} className="text-green-500" />
                    </div>
                    <div className="flex-1">
                      <h4 className="text-xs font-bold text-slate-700 mb-1">AI Analysis</h4>
                      <p className="text-[11px] text-slate-600 mb-1.5">{selectedCluster.llm_summary}</p>
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
                                        {new Date(item.timestamp * 1000).toLocaleTimeString([], {hour12: false, fractionalSecondDigits: 2})}
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

      {/* Header Block */}
      <div className="flex-shrink-0 flex flex-col md:flex-row md:items-center md:justify-between gap-4 px-1">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{t('timeline.title')}</h1>
          <p className="text-[10px] text-slate-500 font-mono mt-0.5">{currentTask?.image_path || taskId}</p>
        </div>
        <div className="flex items-center space-x-2 bg-slate-100 p-1 rounded-xl">
           <Button variant={viewMode === 'timeline' ? 'primary' : 'ghost'} size="sm" onClick={() => updateParams({ view: 'timeline' })} icon={Clock}>{t('timeline.view.list')}</Button>
           <Button variant={viewMode === 'table' ? 'primary' : 'ghost'} size="sm" onClick={() => updateParams({ view: 'table' })} icon={FileText}>{t('timeline.view.table')}</Button>
        </div>
      </div>

      <div className="flex-1 flex flex-col lg:flex-row gap-6 min-h-0 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-full lg:w-80 flex flex-col min-h-0 space-y-4 overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-slate-200">
          <div className="flex-shrink-0 bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden flex flex-col">
            <div className="p-3 border-b border-slate-50 flex justify-between items-center bg-slate-50/30">
                <span className="text-[11px] font-bold text-slate-600 flex items-center uppercase tracking-wider"><Calendar className="w-3.5 h-3.5 mr-1.5 text-primary-500"/> {t('timeline.stats.distribution')}</span>
                {selectedDate && <button onClick={() => updateParams({date: ''})} className="text-[10px] bg-primary-50 text-primary-600 px-2 py-0.5 rounded-full font-bold hover:bg-primary-100 transition-colors">{selectedDate} ×</button>}
            </div>
            <div className="p-2 overflow-x-auto scrollbar-hide">
              <div className="h-32" style={{ minWidth: (distributionData?.length * 20 || 300) + 'px' }}>
                {distributionData ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={distributionData} onClick={handleBarClick} margin={{top: 5, right: 5, left: -25, bottom: 0}}>
                      <XAxis dataKey="date" hide />
                      <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', fontSize: '10px', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                      <Bar dataKey="CREATED" stackId="a" fill="#10b981" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="MODIFIED" stackId="a" fill="#3b82f6" />
                      <Bar dataKey="DELETED" stackId="a" fill="#ef4444" />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <div className="h-full flex items-center justify-center text-[10px] text-slate-400">Syncing...</div>}
              </div>
            </div>
          </div>

          <Card title={t('timeline.filter.type')} icon={Filter} className="bg-white flex-shrink-0">
            <div className="space-y-4 p-1">
              <div>
                <label className="text-[10px] font-bold text-slate-400 uppercase mb-1.5 block tracking-widest">{t('timeline.filter.type')}</label>
                <select 
                    value={eventType} 
                    onChange={(e) => updateParams({ type: e.target.value, page: 1 })}
                    className="w-full rounded-lg border-slate-200 text-xs shadow-sm focus:ring-primary-500"
                >
                    <option value="">{t('timeline.filter.all')}</option>
                    <option value="CREATED">{t('timeline.filter.created')}</option>
                    <option value="MODIFIED">{t('timeline.filter.modified')}</option>
                    <option value="DELETED">{t('timeline.filter.deleted')}</option>
                </select>
              </div>

              <div className="flex items-center space-x-3 p-2.5 bg-slate-50/50 rounded-xl border border-slate-100">
                <input 
                  type="checkbox" 
                  checked={isClustered} 
                  onChange={(e) => updateParams({ cluster: e.target.checked ? 'true' : 'false', page: 1 })}
                  className="rounded text-primary-600 w-4 h-4 cursor-pointer"
                />
                <div className="text-xs">
                  <div className="font-bold text-slate-700 leading-none">{t('timeline.filter.cluster')}</div>
                  <div className="text-slate-400 mt-1 scale-90 origin-left">{t('timeline.filter.cluster_desc')}</div>
                </div>
              </div>

              <div className="pt-2 px-1">
                <div className="flex justify-between text-[11px] text-slate-500">
                    <span>{t('timeline.stats.matches')}:</span>
                    <span className="font-bold text-slate-900">{totalCount.toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-[11px] text-slate-500 mt-1.5">
                    <span>{t('timeline.stats.navigator')}:</span>
                    <span className="font-mono text-primary-600 font-bold">{currentPage} / {totalPages || 1}</span>
                </div>
              </div>

              {(eventType || selectedDate) && (
                <Button variant="outline" size="sm" fullWidth onClick={resetFilters} icon={X} className="text-[11px] border-dashed">{t('timeline.filter.reset')}</Button>
              )}
            </div>
          </Card>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col min-h-0 bg-white rounded-2xl border border-slate-100 shadow-sm relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 bg-white/80 z-50 flex flex-col items-center justify-center backdrop-blur-sm">
                <Spinner size="lg" />
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mt-3">{t('timeline.status.loading')}</span>
            </div>
          )}
          
          <div className="flex-1 min-h-0 overflow-hidden">
            {events.length === 0 && !loading ? (
                <div className="h-full flex items-center justify-center text-slate-400 italic text-sm">{t('timeline.status.empty')}</div>
            ) : viewMode === 'timeline' ? (
                <Virtuoso
                  ref={virtuosoRef}
                  data={events}
                  style={{ height: '100%' }}
                  itemContent={(index, event) => {
                    const isCluster = event.cluster_count > 1;
                    return (
                      <div className="px-6 py-1.5">
                        <div className="relative ml-4 pl-8 border-l-2 border-slate-100 py-2 hover:border-primary-200 transition-colors">
                          <div className={`absolute -left-[9px] top-6 w-4 h-4 rounded-full border-2 border-white shadow-sm z-10 ${
                            event.event_type === 'CREATED' ? 'bg-emerald-500' :
                            event.event_type === 'MODIFIED' ? 'bg-blue-500' :
                            event.event_type === 'DELETED' ? 'bg-rose-500' : 'bg-slate-400'
                          }`} />
                          
                          <div 
                            className={`bg-white rounded-xl border ${isCluster ? 'border-primary-200 bg-primary-50/5 cursor-pointer' : 'border-slate-100'} p-4 shadow-sm hover:shadow-md transition-all group`}
                            onClick={() => isCluster && handleOpenCluster(event)}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                              <div className="flex items-center space-x-2">
                                <span className="text-[12px] font-bold text-slate-800 font-mono tracking-tight">
                                  {isCluster 
                                    ? `${formatTimeOnly(event.timestamp)} - ${formatTimeOnly(event.end_timestamp)}`
                                    : formatTimestamp(event.timestamp)}
                                </span>
                                <Badge variant={
                                  event.event_type === 'CREATED' ? 'green' :
                                  event.event_type === 'MODIFIED' ? 'blue' :
                                  event.event_type === 'DELETED' ? 'red' : 'gray'
                                } className="text-[9px] px-1.5 py-0 uppercase font-black">
                                  {event.event_type}
                                </Badge>
                                {isCluster && (
                                  <Badge variant="blue" icon={Layers} className="text-[9px] px-1.5 py-0 font-bold">
                                    {event.cluster_count} {t('timeline.node.items')}
                                  </Badge>
                                )}
                                {isCluster && event.llm_summary && (
                                  <Badge variant="green" icon={CheckCircle2} className="text-[9px] px-1.5 py-0 font-bold">
                                    AI Analyzed
                                  </Badge>
                                )}
                              </div>
                              {isCluster && <ArrowRight size={14} className="text-primary-400 opacity-0 group-hover:opacity-100 transition-opacity" />}
                              {!isCluster && <span className="text-[10px] font-mono text-slate-400 opacity-60">ID:{event.inode}</span>}
                            </div>
                            
                            {isCluster ? (
                              <div className="space-y-1.5">
                                <div className="flex items-center text-[11px] font-bold text-slate-500">
                                  <Folder className="w-3 h-3 mr-1.5 text-primary-400" /> {event.parent_directory || '/'}
                                </div>
                                <p className="text-[11px] text-slate-600 truncate bg-slate-50 p-1.5 rounded-lg border border-slate-100 border-dashed font-mono">
                                  {t('timeline.node.sample')}: {event.file_path.split('/').pop()}
                                </p>
                              </div>
                            ) : (
                              <p className="text-[13px] text-slate-700 font-medium break-all mb-1 leading-relaxed">
                                {event.file_path}
                              </p>
                            )}
                            
                            <div className="flex items-center space-x-4 text-[10px] text-slate-400 mt-2.5 pt-2 border-t border-slate-50">
                               <div className="flex items-center">
                                <FileText className="w-3 h-3 mr-1 opacity-70" />
                                {isCluster && <span className="mr-1">[{event.cluster_count} {t('timeline.node.items')}]</span>}
                                {formatFileSize(event.file_size)} {isCluster ? `(${t('timeline.node.total')})` : ''}
                              </div>
                              {event.file_type && <span className="bg-slate-100 px-1.5 py-0.5 rounded text-[9px] font-black uppercase text-slate-500 tracking-tighter">{event.file_type}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  }}
                />
            ) : (
                <div className="h-full overflow-auto scrollbar-thin scrollbar-thumb-slate-200">
                    <table className="min-w-full divide-y divide-slate-200">
                      <thead className="bg-slate-50 sticky top-0 z-10">
                        <tr>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('timeline.stats.matches')}</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">{t('timeline.filter.type')}</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">Path</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">Size</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-slate-100">
                        {events.map((event, idx) => (
                          <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                            <td className="px-4 py-3 whitespace-nowrap text-[11px] font-mono text-slate-700">{formatTimestamp(event.timestamp)}</td>
                            <td className="px-4 py-3">
                                <Badge variant={event.event_type === 'CREATED' ? 'green' : event.event_type === 'MODIFIED' ? 'blue' : 'red'} className="text-[9px] font-black">{event.event_type}</Badge>
                            </td>
                            <td className="px-4 py-3 text-[11px] text-slate-600 truncate max-w-sm font-medium">{event.file_path}</td>
                            <td className="px-4 py-3 text-[11px] text-slate-500 font-mono">{formatFileSize(event.file_size)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                </div>
            )}
          </div>

          {/* Sticky Footer Pagination */}
          <footer className="flex-shrink-0 flex items-center justify-between border-t border-slate-100 p-3 bg-slate-50/80 backdrop-blur-sm">
                <Button variant="ghost" size="sm" disabled={currentPage === 1} onClick={() => updateParams({ page: currentPage - 1 })} icon={ChevronLeft} className="hover:bg-white shadow-sm">PREV</Button>
                <div className="text-[10px] text-slate-500 font-black bg-white px-4 py-1.5 rounded-full border border-slate-200 shadow-sm tracking-widest uppercase">
                    {t('timeline.stats.navigator')} {currentPage} / {totalPages || 1}
                </div>
                <Button variant="ghost" size="sm" disabled={currentPage === totalPages || totalPages === 0} onClick={() => updateParams({ page: currentPage + 1 })} icon={ChevronRight} iconPosition="right" className="hover:bg-white shadow-sm">NEXT</Button>
          </footer>
        </main>
      </div>
    </div>
  );
};

export default Timeline;
