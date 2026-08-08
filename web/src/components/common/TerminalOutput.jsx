import { useState, useEffect, useRef } from 'react';
import Card from './Card';
import Button from './Button';
import { useWebSocket } from '../../hooks/useWebSocket';
import { useTranslation } from '../../hooks/useTranslation';

// 动态推导服务地址，跨机访问时用浏览器当前 host。
const PYTHON_BASE = `http://${window.location.hostname}:8090`;
const WS_BASE = `ws://${window.location.hostname}:8666`;
// 端口从地址中提取，避免硬编码数字与实际端口不一致。
const CPP_PORT = new URL(`http://${window.location.hostname}:8666`).port;
const PYTHON_PORT = new URL(PYTHON_BASE).port;

const TERMINAL_COLORS = {
  cpp: '#10b981',    // green
  python: '#3b82f6', // blue
  web: '#f59e0b',    // amber
};

// Pseudo-persistence for web logs during the session
if (!window.forensics_web_logs) {
  window.forensics_web_logs = [];
}

const TerminalOutput = ({ taskId = null, maxHeight = '400px' }) => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('cpp');
  const [logs, setLogs] = useState({
    cpp: [],
    python: [],
    web: window.forensics_web_logs || [],
  });
  const [autoScroll, setAutoScroll] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSourceRef = useRef(null);
  
  const terminalEndRefs = {
    cpp: useRef(null),
    python: useRef(null),
    web: useRef(null),
  };

  // Scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && terminalEndRefs[activeTab]?.current) {
      terminalEndRefs[activeTab].current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, activeTab, autoScroll]);

  const startStreaming = (source) => {
    if (eventSourceRef.current) eventSourceRef.current.close();
    if (source === 'web') return;

    const endpoints = {
      cpp: `${PYTHON_BASE}/api/system/logs-stream/cpp`,
      python: `${PYTHON_BASE}/api/system/logs-stream/python`,
    };

    const url = endpoints[source];
    if (!url) return;

    setIsStreaming(true);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        setLogs(prev => ({
          ...prev,
          [source]: [...prev[source].slice(-499), entry],
        }));
      } catch (e) {
        setLogs(prev => ({
          ...prev,
          [source]: [...prev[source].slice(-499), { timestamp: '', level: 'INFO', message: event.data }],
        }));
      }
    };

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
    };
  };

  // Fetch logs via REST API
  const fetchLogs = async (source) => {
    if (source === 'web') return;
    try {
      const endpoints = {
        cpp: `${PYTHON_BASE}/api/system/logs/cpp`,
        python: `${PYTHON_BASE}/api/system/logs/python`,
      };

      const endpoint = endpoints[source];
      if (!endpoint) return;

      const response = await fetch(endpoint);
      if (response.ok) {
        const data = await response.json();
        setLogs(prev => ({
          ...prev,
          [source]: data.logs || [],
        }));
      }
    } catch (error) {
      console.error(`Failed to fetch ${source} logs:`, error);
    }
  };

  // Initial log fetch
  useEffect(() => {
    fetchLogs('cpp');
    fetchLogs('python');
  }, []);

  // Capture web logs locally
  useEffect(() => {
    const originalLog = console.log;
    const originalError = console.error;
    const originalWarn = console.warn;

    const addLog = (level, ...args) => {
      const timestamp = new Date().toISOString();
      const message = args.map(arg =>
        typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg)
      ).join(' ');

      const entry = { timestamp, level, message };
      window.forensics_web_logs.push(entry);
      if (window.forensics_web_logs.length > 500) window.forensics_web_logs.shift();
      
      setLogs(prev => ({
        ...prev,
        web: [...window.forensics_web_logs],
      }));
    };

    console.log = (...args) => {
      addLog('INFO', ...args);
      originalLog.apply(console, args);
    };

    console.error = (...args) => {
      addLog('ERROR', ...args);
      originalError.apply(console, args);
    };

    console.warn = (...args) => {
      addLog('WARN', ...args);
      originalWarn.apply(console, args);
    };

    return () => {
      console.log = originalLog;
      console.error = originalError;
      console.warn = originalWarn;
    };
  }, []);

  // WebSocket handlers for real-time logs
  const wsHandlers = {
    cpp_log: (data) => {
      setLogs(prev => ({
        ...prev,
        cpp: [...prev.cpp.slice(-200), data], // Keep last 200
      }));
    },
    python_log: (data) => {
      setLogs(prev => ({
        ...prev,
        python: [...prev.python.slice(-200), data],
      }));
    },
  };

  const { connected } = useWebSocket(
    taskId ? `${WS_BASE}/ws/tasks/${taskId}/logs` : `${WS_BASE}/ws/logs`,
    wsHandlers,
    { enabled: !!taskId }
  );

  useEffect(() => {
    setIsStreaming(connected);
  }, [connected]);

  const handleRefresh = () => {
    fetchLogs('cpp');
    fetchLogs('python');
  };

  const handleClear = () => {
    setLogs({
      cpp: [],
      python: [],
      web: [],
    });
  };

  const formatLogEntry = (entry, index) => {
    const levelColors = {
      INFO: 'text-slate-300',
      ERROR: 'text-red-400',
      WARN: 'text-yellow-400',
      DEBUG: 'text-slate-500',
    };

    const levelColor = levelColors[entry.level] || 'text-slate-300';

    return (
      <div key={index} className={`flex gap-2 text-sm ${levelColor} font-mono`}>
        <span className="text-slate-500 shrink-0">
          {entry.timestamp?.split('T')[1]?.split('.')[0] || ''}
        </span>
        <span className="shrink-0 w-16">[{entry.level}]</span>
        <span className="break-all">{entry.message}</span>
      </div>
    );
  };

  const tabs = [
    { id: 'cpp', label: 'C++ Backend', color: TERMINAL_COLORS.cpp },
    { id: 'python', label: 'Python Service', color: TERMINAL_COLORS.python },
    { id: 'web', label: 'Web Frontend', color: TERMINAL_COLORS.web },
  ];

  return (
    <Card className="mt-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            🖥️ {t('terminal.title')}
          </h3>
          {isStreaming && (
            <span className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              Live
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
            />
            Auto-scroll
          </label>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefresh}
            className="px-3 py-1"
          >
            🔄 Refresh
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleClear}
            className="px-3 py-1"
          >
            🗑️ {t('terminal.clear')}
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-3 border-b border-slate-200 dark:border-slate-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors relative ${
              activeTab === tab.id
                ? 'text-slate-900 dark:text-white'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5"
                style={{ backgroundColor: tab.color }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Terminal Content */}
      <div
        className="bg-slate-950 rounded-xl p-4 overflow-y-auto font-mono text-sm"
        style={{ maxHeight }}
      >
        {logs[activeTab].length === 0 ? (
          <div className="text-slate-500 text-center py-8">
            {t('timeline.status.empty')}
          </div>
        ) : (
          <>
            <div className="space-y-1">
              {logs[activeTab].map((entry, index) => formatLogEntry(entry, index))}
            </div>
            <div ref={terminalEndRefs[activeTab]} />
          </>
        )}
      </div>

      {/* Status Bar */}
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>
          {logs[activeTab].length} entries
        </span>
        <span>
          {activeTab === 'cpp' && `Port ${CPP_PORT}`}
          {activeTab === 'python' && `Port ${PYTHON_PORT}`}
          {activeTab === 'web' && 'Browser Console'}
        </span>
      </div>
    </Card>
  );
};

export default TerminalOutput;
