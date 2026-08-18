
import { useState, useEffect, useRef, useCallback } from 'react';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';

// 动态推导 Python 服务地址，跨机访问时用浏览器当前 host。
const PYTHON_BASE = `http://${window.location.hostname}:8090`;

const Logs = () => {
  const [activeService, setActiveService] = useState('python');
  const [logs, setLogs] = useState([]);
  const [isAutoScroll, setIsAutoScroll] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const logContainerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  const fetchLogs = useCallback(async (service) => {
    try {
      const response = await fetch(`${PYTHON_BASE}/api/system/logs/${service}?lines=200`);
      const data = await response.json();
      if (data.logs) {
        setLogs(data.logs);
      }
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      setLogs(['Error: Failed to fetch logs from server.']);
    }
  }, []);

  const startStreaming = useCallback((service) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const eventSource = new EventSource(`${PYTHON_BASE}/api/system/logs-stream/${service}`);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      setLogs((prevLogs) => [...prevLogs.slice(-499), event.data]);
    };

    eventSource.onerror = (error) => {
      console.error('EventSource error:', error);
      setIsStreaming(false);
      eventSource.close();
    };
  }, []);

  const stopStreaming = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => {
    fetchLogs(activeService);
    if (isStreamingRef.current) {
      startStreaming(activeService);
    }
    return stopStreaming;
  }, [activeService, fetchLogs, startStreaming, stopStreaming]);

  useEffect(() => {
    if (isAutoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, isAutoScroll]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white">系统日志监控</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">实时查看 C++ 后端和 Python 服务的终端输出</p>
        </div>
        <div className="flex space-x-2">
          <Button 
            variant={activeService === 'python' ? 'primary' : 'outline'}
            onClick={() => setActiveService('python')}
          >
            Python 服务
          </Button>
          <Button 
            variant={activeService === 'cpp' ? 'primary' : 'outline'}
            onClick={() => setActiveService('cpp')}
          >
            C++ 后端
          </Button>
        </div>
      </div>

      <Card className="flex flex-col h-[600px] p-0 overflow-hidden bg-slate-900 border-slate-800">
        <div className="flex items-center justify-between px-4 py-2 bg-slate-800 border-b border-slate-700">
          <div className="flex items-center space-x-2">
            <div className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-green-500 animate-pulse' : 'bg-yellow-500'}`}></div>
            <span className="text-xs font-mono text-slate-300 uppercase">
              {activeService} service log
            </span>
          </div>
          <div className="flex items-center space-x-4">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input 
                type="checkbox" 
                checked={isAutoScroll} 
                onChange={(e) => setIsAutoScroll(e.target.checked)}
                className="rounded border-slate-600 bg-slate-700 text-primary-500 focus:ring-primary-500"
              />
              <span className="text-xs text-slate-400">自动滚动</span>
            </label>
            <button 
              onClick={() => isStreaming ? stopStreaming() : startStreaming(activeService)}
              className="text-xs text-slate-300 hover:text-white transition-colors"
            >
              {isStreaming ? '停止实时同步' : '开启实时同步'}
            </button>
            <button 
              onClick={() => setLogs([])}
              className="text-xs text-slate-300 hover:text-white transition-colors"
            >
              清屏
            </button>
          </div>
        </div>
        
        <div 
          ref={logContainerRef}
          className="flex-1 p-4 overflow-y-auto font-mono text-sm text-slate-300 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent"
        >
          {logs.length > 0 ? (
            logs.map((log, index) => (
              <div key={index} className="whitespace-pre-wrap mb-1 hover:bg-white/5 px-1 rounded">
                <span className="text-slate-500 mr-2 select-none">{(index + 1).toString().padStart(4, '0')}</span>
                {log}
              </div>
            ))
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500 italic">
              等待日志输出...
            </div>
          )}
        </div>
      </Card>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card title="诊断说明">
          <ul className="text-sm space-y-2 text-slate-600 dark:text-slate-400">
            <li className="flex items-start">
              <span className="text-primary-500 mr-2">•</span>
              <span><strong>Python 服务:</strong> 包含 LLM 调度、知识图谱摄入、报告生成等逻辑。</span>
            </li>
            <li className="flex items-start">
              <span className="text-primary-500 mr-2">•</span>
              <span><strong>C++ 后端:</strong> 包含磁盘镜像挂载、文件系统解析、物理文件提取等底层操作。</span>
            </li>
          </ul>
        </Card>
        <Card title="常用排查关键词">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">ERROR</Badge>
            <Badge variant="outline">Failed</Badge>
            <Badge variant="outline">Timeout</Badge>
            <Badge variant="outline">LLM Response</Badge>
            <Badge variant="outline">Extracting</Badge>
            <Badge variant="outline">404 Not Found</Badge>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default Logs;
