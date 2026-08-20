import { useState } from 'react';
import { Link2 } from 'lucide-react';
import Button from '../../../components/common/Button';
import Modal from '../../../components/common/Modal';
import { linkEventEvidence } from '../../../services/investigationService';

const normalizePath = (value) => value.replaceAll('\\', '/').replace(/\/{2,}/g, '/').replace(/\/$/, '');

export default function EvidencePicker({ taskId, eventId, open, onClose, onLinked }) {
  const [path, setPath] = useState('');
  const [role, setRole] = useState('supporting');
  const [rationale, setRationale] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const link = async () => {
    const normalized = normalizePath(path.trim());
    if (!normalized) return;
    setLoading(true); setError('');
    try {
      await linkEventEvidence(taskId, eventId, {
        evidence_key: `file:${normalized}`,
        role,
        rationale: rationale || null,
      });
      setPath(''); setRationale('');
      onLinked?.(); onClose();
    } catch (err) {
      setError(err.message || '关联证据失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal isOpen={open} onClose={onClose} title="添加关联证据" size="lg">
      <p className="text-sm text-slate-500">MVP 支持 File Evidence。输入 files.db 中的完整取证路径，服务端会在当前 task 内验证并生成稳定 Evidence Key。</p>
      <label className="mt-4 block text-sm font-medium">取证文件路径</label>
      <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\\Users\\Alice\\secret.xlsx 或 /docs/secret.xlsx" className="mt-1 w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50" />
      <label className="mt-4 block text-sm font-medium">Evidence Role</label>
      <select value={role} onChange={(e) => setRole(e.target.value)} className="mt-1 w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50">
        <option value="primary">Primary</option><option value="supporting">Supporting</option><option value="context">Context</option><option value="contradicting">Contradicting</option>
      </select>
      <label className="mt-4 block text-sm font-medium">关联理由（可选）</label>
      <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={3} className="mt-1 w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50" />
      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
      <div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>取消</Button><Button icon={Link2} loading={loading} disabled={!path.trim()} onClick={link}>关联证据</Button></div>
    </Modal>
  );
}
