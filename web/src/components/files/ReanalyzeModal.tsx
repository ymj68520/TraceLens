import { useState, type FormEvent } from 'react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';

interface ReanalyzeModalProps {
  fileCount: number;
  running: boolean;
  onSubmit: (hint: string) => Promise<void>;
  onClose: () => void;
}

export default function ReanalyzeModal({ fileCount, running, onSubmit, onClose }: ReanalyzeModalProps) {
  const [hint, setHint] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await onSubmit(hint.trim());
  };

  return (
    <Modal open onClose={onClose} title="二次分析" width="md">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-xs text-ink-500 dark:text-ink-400">
          将对已选中的 <span className="font-semibold text-ink-800 dark:text-ink-200">{fileCount}</span> 个文件重新进行 LLM 分析。
        </p>
        <div>
          <label className="field-label" htmlFor="reanalyze-hint">补充说明（可选）</label>
          <textarea
            id="reanalyze-hint"
            rows={4}
            value={hint}
            onChange={(e) => setHint(e.target.value)}
            className="input resize-y"
            placeholder="例如：重点关注与勒索软件相关的文件、检查是否包含敏感信息…"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose} disabled={running}>取消</Button>
          <Button variant="primary" type="submit" disabled={running}>
            {running ? '提交中…' : '开始二次分析'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
