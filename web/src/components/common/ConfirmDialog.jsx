/**
 * ConfirmDialog
 *
 * A premium confirmation dialog that replaces `window.confirm()`.
 * Supports danger/warning/info variants, an optional checkbox, and
 * smooth framer-motion animations to match the rest of the UI.
 *
 * Usage:
 *   <ConfirmDialog
 *     open={showConfirm}
 *     onConfirm={handleConfirm}
 *     onCancel={() => setShowConfirm(false)}
 *     title="删除任务"
 *     message="此操作不可撤销，确定要删除该任务吗？"
 *     variant="danger"
 *     confirmText="删除"
 *     cancelText="取消"
 *   />
 *
 *   With checkbox:
 *   <ConfirmDialog
 *     ...
 *     checkboxLabel="同时删除关联的 3 个分析任务"
 *     onConfirm={(checked) => handleConfirm(checked)}
 *   />
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Trash2, Info, X } from 'lucide-react';

const VARIANTS = {
  danger: {
    icon: Trash2,
    iconBg: 'bg-rose-100 dark:bg-rose-900/40',
    iconColor: 'text-rose-600 dark:text-rose-400',
    confirmBtn:
      'bg-gradient-to-r from-rose-600 to-rose-500 hover:from-rose-500 hover:to-rose-400 text-white shadow-md focus:ring-rose-500',
    ring: 'ring-rose-500/20',
  },
  warning: {
    icon: AlertTriangle,
    iconBg: 'bg-amber-100 dark:bg-amber-900/40',
    iconColor: 'text-amber-600 dark:text-amber-400',
    confirmBtn:
      'bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-white shadow-md focus:ring-amber-500',
    ring: 'ring-amber-500/20',
  },
  info: {
    icon: Info,
    iconBg: 'bg-sky-100 dark:bg-sky-900/40',
    iconColor: 'text-sky-600 dark:text-sky-400',
    confirmBtn:
      'bg-gradient-to-r from-sky-600 to-sky-500 hover:from-sky-500 hover:to-sky-400 text-white shadow-md focus:ring-sky-500',
    ring: 'ring-sky-500/20',
  },
};

export default function ConfirmDialog({
  open = false,
  onConfirm,
  onCancel,
  title = '确认操作',
  message = '此操作不可撤销，确定要继续吗？',
  confirmText = '确认',
  cancelText = '取消',
  variant = 'danger',
  loading = false,
  checkboxLabel = '',
  checkboxDefaultChecked = false,
}) {
  const [checked, setChecked] = useState(checkboxDefaultChecked);
  const v = VARIANTS[variant] || VARIANTS.danger;
  const IconComponent = v.icon;

  // Reset checkbox state when dialog opens
  useEffect(() => {
    if (open) setChecked(checkboxDefaultChecked);
  }, [open, checkboxDefaultChecked]);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [open]);

  // Keyboard: Escape to cancel
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Escape' && open && !loading) onCancel?.();
    },
    [open, loading, onCancel]
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !loading) onCancel?.();
  };

  const handleConfirm = () => {
    if (loading) return;
    onConfirm?.(checked);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          onClick={handleBackdropClick}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          {/* Panel */}
          <motion.div
            className="relative glass-strong rounded-2xl shadow-2xl w-full max-w-md overflow-hidden"
            initial={{ opacity: 0, scale: 0.9, y: 30 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 30 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            {/* Close button */}
            <motion.button
              type="button"
              className="absolute top-3 right-3 p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100/50 dark:hover:text-slate-300 dark:hover:bg-slate-700/50 transition-colors z-10"
              onClick={onCancel}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              disabled={loading}
            >
              <X size={18} />
            </motion.button>

            {/* Content */}
            <div className="px-6 pt-6 pb-2">
              <div className="flex items-start gap-4">
                {/* Icon */}
                <div className={`flex-shrink-0 p-3 rounded-xl ${v.iconBg}`}>
                  <IconComponent className={`w-6 h-6 ${v.iconColor}`} />
                </div>

                {/* Text */}
                <div className="flex-1 min-w-0 pt-0.5">
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white leading-tight">
                    {title}
                  </h3>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
                    {message}
                  </p>
                </div>
              </div>

              {/* Optional checkbox */}
              {checkboxLabel && (
                <label className="flex items-center gap-3 mt-4 ml-1 p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/40 cursor-pointer group select-none">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => setChecked(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 dark:border-slate-600 text-rose-600 focus:ring-rose-500 dark:bg-slate-700 cursor-pointer"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300 font-medium group-hover:text-slate-900 dark:group-hover:text-white transition-colors">
                    {checkboxLabel}
                  </span>
                </label>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 mt-2 border-t border-white/10 dark:border-slate-700/40">
              <motion.button
                type="button"
                className="px-4 py-2 text-sm font-semibold rounded-xl text-slate-700 dark:text-slate-300 bg-slate-200/80 dark:bg-slate-700/60 hover:bg-slate-300/80 dark:hover:bg-slate-600/60 transition-all disabled:opacity-50"
                onClick={onCancel}
                whileHover={!loading ? { scale: 1.02 } : {}}
                whileTap={!loading ? { scale: 0.97 } : {}}
                disabled={loading}
              >
                {cancelText}
              </motion.button>
              <motion.button
                type="button"
                className={`px-5 py-2 text-sm font-semibold rounded-xl transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 dark:focus:ring-offset-slate-900 disabled:opacity-50 disabled:cursor-not-allowed ${v.confirmBtn}`}
                onClick={handleConfirm}
                whileHover={!loading ? { scale: 1.02 } : {}}
                whileTap={!loading ? { scale: 0.97 } : {}}
                disabled={loading}
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    处理中...
                  </span>
                ) : (
                  confirmText
                )}
              </motion.button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
