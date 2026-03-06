import { useState } from 'react';
import TerminalOutput from '../components/common/TerminalOutput';
import Card from '../components/common/Card';
import Button from '../components/common/Button';

const Terminal = () => {
  const [selectedTask, setSelectedTask] = useState(null);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white">
          🖥️ Terminal Output
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-300">
          Real-time logs from all services
        </p>
      </div>

      {/* Info Card */}
      <Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-xl">
            <div className="text-sm font-medium text-green-800 dark:text-green-300">
              C++ Backend
            </div>
            <div className="text-2xl font-bold text-green-900 dark:text-green-100 mt-1">
              Port 8080
            </div>
            <div className="text-xs text-green-600 dark:text-green-400 mt-1">
              Task Management, Forensics API
            </div>
          </div>

          <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-xl">
            <div className="text-sm font-medium text-blue-800 dark:text-blue-300">
              Python Service
            </div>
            <div className="text-2xl font-bold text-blue-900 dark:text-blue-100 mt-1">
              Port 8090
            </div>
            <div className="text-xs text-blue-600 dark:text-blue-400 mt-1">
              LLM Analysis, Knowledge Graph
            </div>
          </div>

          <div className="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-xl">
            <div className="text-sm font-medium text-amber-800 dark:text-amber-300">
              Web Frontend
            </div>
            <div className="text-2xl font-bold text-amber-900 dark:text-amber-100 mt-1">
              Port 3000
            </div>
            <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              Browser Console, Client Logs
            </div>
          </div>
        </div>

        <div className="mt-4 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl">
          <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-2">
            📌 Quick Actions
          </h3>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => window.open('http://localhost:8080/api/system/health', '_blank')}
            >
              Check C++ Health
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => window.open('http://localhost:8090/health', '_blank')}
            >
              Check Python Health
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => window.open('http://localhost:8090/docs', '_blank')}
            >
              Python API Docs
            </Button>
          </div>
        </div>
      </Card>

      {/* Terminal Output */}
      <TerminalOutput maxHeight="600px" />
    </div>
  );
};

export default Terminal;
