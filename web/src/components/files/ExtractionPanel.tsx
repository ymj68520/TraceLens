import { useEffect, useRef, useState } from 'react';
import { HardDriveDownload } from 'lucide-react';
import { startExtraction, pollExtractionStatus } from '../../services/extractionService';
import Button from '../ui/Button';
import ProgressBar from '../ui/ProgressBar';
import { useToast } from '../ui/Toast';
import { errorMessage } from '../../lib/utils';

interface ExtractionPanelProps {
  taskId: string;
}

type ExtractStatus = 'idle' | 'running' | 'completed' | 'failed';

export default function ExtractionPanel({ taskId }: ExtractionPanelProps) {
  const toast = useToast();
  const [mode, setMode] = useState<'all' | 'extension' | 'name' | 'deleted'>('all');
  const [pattern, setPattern] = useState('');
  const [outputDir, setOutputDir] = useState('extracted_files');
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [status, setStatus] = useState<ExtractStatus>('idle');
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  // Abort any in-flight poll when switching tasks or unmounting.
  useEffect(
    () => () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    },
    [taskId],
  );

  const handleStart = async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setStatus('running');
    setMessage('正在启动提取…');
    setProgress(0);

    try {
      const { job_id } = await startExtraction(taskId, {
        mode,
        pattern,
        outputDir,
        includeDeleted,
        overwrite,
      });
      await pollExtractionStatus(
        job_id,
        (s) => {
          const p = (s.progress as number) ?? 0;
          setProgress(p);
          setMessage((s.message as string) || `进度 ${Math.round(p)}%`);
        },
        1000,
        { taskId, signal: controller.signal },
      );
      setStatus('completed');
      setMessage('提取完成');
      toast.success('文件提取完成');
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setStatus('failed');
      setMessage(errorMessage(err));
      toast.error(`提取失败：${errorMessage(err)}`);
    }
  };

  return (
    <div className="card card-pad space-y-4 max-w-2xl">
      <div>
        <h3 className="card-title flex items-center gap-1.5">
          <HardDriveDownload size={15} className="text-ink-400" />
          文件提取
        </h3>
        <p className="card-subtitle mt-0.5">将镜像内文件提取到宿主机目录</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">提取模式</label>
          <select
            className="select"
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
          >
            <option value="all">全部文件</option>
            <option value="extension">按扩展名</option>
            <option value="name">按文件名</option>
            <option value="deleted">仅已删除</option>
          </select>
        </div>
        {(mode === 'extension' || mode === 'name') && (
          <div>
            <label className="field-label">匹配模式</label>
            <input
              type="text"
              className="input"
              placeholder={mode === 'extension' ? '.txt,.log' : '*report*'}
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
            />
          </div>
        )}
        <div>
          <label className="field-label">输出目录</label>
          <input
            type="text"
            className="input font-mono text-xs"
            value={outputDir}
            onChange={(e) => setOutputDir(e.target.value)}
          />
        </div>
        <div className="flex items-end gap-4 pb-1">
          <label className="flex items-center gap-1.5 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={includeDeleted}
              onChange={(e) => setIncludeDeleted(e.target.checked)}
            />
            包含已删除
          </label>
          <label className="flex items-center gap-1.5 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
            />
            覆盖已有文件
          </label>
        </div>
      </div>

      {status !== 'idle' && (
        <div className="space-y-1.5">
          <ProgressBar value={progress} showLabel />
          <p className="text-2xs text-ink-500 dark:text-ink-400">{message}</p>
        </div>
      )}

      <Button variant="primary" onClick={handleStart} disabled={status === 'running'}>
        {status === 'running' ? '提取中…' : '开始提取'}
      </Button>
    </div>
  );
}
