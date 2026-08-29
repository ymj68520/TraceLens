import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import Modal from './Modal';
import Button from './Button';
import Spinner from './Spinner';

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title = '确认操作',
  message,
  confirmText = '确认',
  cancelText = '取消',
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await onConfirm();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open={open} onClose={onCancel} width="sm" title={title}>
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 p-2 rounded-md ${danger ? 'bg-rose-50 text-rose-600 dark:bg-rose-500/10' : 'bg-amber-50 text-amber-600 dark:bg-amber-500/10'}`}>
          <AlertTriangle size={18} />
        </div>
        <p className="text-sm text-ink-700 dark:text-ink-300 leading-relaxed">{message}</p>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button onClick={onCancel} disabled={loading}>
          {cancelText}
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={handleConfirm} disabled={loading}>
          {loading ? <Spinner size="sm" /> : confirmText}
        </Button>
      </div>
    </Modal>
  );
}

export default ConfirmDialog;
