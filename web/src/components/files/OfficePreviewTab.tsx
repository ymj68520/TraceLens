import { useState, type FormEvent } from 'react';
import { FileText } from 'lucide-react';
import { parseFile } from '../../services/officeService';
import Button from '../ui/Button';
import { LoadingBlock } from '../ui/Spinner';
import EmptyState from '../ui/EmptyState';
import { errorMessage } from '../../lib/utils';

interface OfficePreviewTabProps {
  taskId: string;
}

interface ParsedOffice {
  text?: string;
  content?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export default function OfficePreviewTab({ taskId }: OfficePreviewTabProps) {
  const [path, setPath] = useState('');
  const [parsing, setParsing] = useState(false);
  const [result, setResult] = useState<ParsedOffice | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleParse = async (e: FormEvent) => {
    e.preventDefault();
    if (!path.trim()) return;
    setParsing(true);
    setError(null);
    setResult(null);
    try {
      const res = (await parseFile(taskId, path.trim())) as ParsedOffice;
      setResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setParsing(false);
    }
  };

  const text = result?.text ?? result?.content ?? '';

  return (
    <div className="card card-pad space-y-4">
      <form onSubmit={handleParse} className="flex gap-2">
        <input
          type="text"
          className="input flex-1 font-mono text-xs"
          placeholder="镜像内 Office 文件路径，如 /Users/xxx/Documents/report.docx"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <Button variant="primary" type="submit" disabled={parsing || !path.trim()}>
          <FileText size={14} />
          {parsing ? '解析中…' : '解析'}
        </Button>
      </form>

      {parsing && <LoadingBlock text="正在解析文档…" />}
      {error && <EmptyState title="解析失败" description={error} />}
      {result && !parsing && (
        <div className="code-block max-h-[480px] whitespace-pre-wrap">
          {text || JSON.stringify(result, null, 2)}
        </div>
      )}
      {!result && !parsing && !error && (
        <EmptyState
          icon={<FileText size={36} />}
          title="Office 文档预览"
          description="输入镜像内的 docx/xlsx/pptx 路径以解析其文本内容。"
        />
      )}
    </div>
  );
}
