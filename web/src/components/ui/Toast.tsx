import { createContext, useCallback, useContext, type ReactNode } from 'react';
import { Toaster, toast } from 'sonner';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import { cx } from '../../lib/utils';

type ToastKind = 'success' | 'error' | 'info';

interface ToastContextValue {
  push: (message: string, kind?: ToastKind) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const kindStyle: Record<ToastKind, string> = {
  success: 'border-emerald-300 dark:border-emerald-500/30',
  error: 'border-rose-300 dark:border-rose-500/30',
  info: 'border-ink-300 dark:border-ink-600',
};

const kindIcon: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />,
  error: <AlertCircle size={16} className="text-rose-500 shrink-0" />,
  info: <Info size={16} className="text-accent-500 shrink-0" />,
};

/**
 * Sonner-backed notifications. The provider keeps the original hook API
 * (push/success/error/info) so call sites don't change; sonner contributes
 * the queue, stacking, hover-to-pause and reduced-motion behaviour.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const push = useCallback((message: string, kind: ToastKind = 'info') => {
    toast.custom(
      (id) => (
        <div
          className={cx(
            'card shadow-pop border-l-4 px-3.5 py-2.5 flex items-start gap-2.5 w-80',
            kindStyle[kind],
          )}
        >
          {kindIcon[kind]}
          <p className="flex-1 text-sm text-ink-800 dark:text-ink-200 leading-snug break-words">
            {message}
          </p>
          <button
            type="button"
            onClick={() => toast.dismiss(id)}
            className="p-0.5 text-ink-400 hover:text-ink-600 dark:hover:text-ink-200"
            aria-label="关闭提示"
          >
            <X size={14} />
          </button>
        </div>
      ),
      { duration: 4000 },
    );
  }, []);

  const value: ToastContextValue = {
    push,
    success: (m) => push(m, 'success'),
    error: (m) => push(m, 'error'),
    info: (m) => push(m, 'info'),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Toaster position="bottom-right" visibleToasts={4} gap={8} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

export default ToastContext;
