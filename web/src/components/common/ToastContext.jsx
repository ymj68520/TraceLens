import { useState, useCallback, useRef } from 'react';
import { ToastContext } from './toastContext';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-react';

let toastId = 0;

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([]);
    const timers = useRef({});

    const removeToast = useCallback((id) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        if (timers.current[id]) {
            clearTimeout(timers.current[id]);
            delete timers.current[id];
        }
    }, []);

    const addToast = useCallback((type, message, duration = 5000) => {
        const id = ++toastId;
        setToasts((prev) => [...prev.slice(-4), { id, type, message }]);
        if (duration > 0) {
            timers.current[id] = setTimeout(() => removeToast(id), duration);
        }
        return id;
    }, [removeToast]);

    const toast = {
        success: (msg, dur) => addToast('success', msg, dur),
        error: (msg, dur) => addToast('error', msg, dur ?? 8000),
        info: (msg, dur) => addToast('info', msg, dur),
        warning: (msg, dur) => addToast('warning', msg, dur ?? 6000),
    };

    const iconMap = {
        success: <CheckCircle size={18} className="text-emerald-400" />,
        error: <XCircle size={18} className="text-rose-400" />,
        info: <Info size={18} className="text-primary-400" />,
        warning: <AlertTriangle size={18} className="text-amber-400" />,
    };

    const borderMap = {
        success: 'border-l-emerald-500',
        error: 'border-l-rose-500',
        info: 'border-l-primary-500',
        warning: 'border-l-amber-500',
    };

    return (
        <ToastContext.Provider value={toast}>
            {children}
            {/* Toast Container */}
            <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 max-w-sm pointer-events-none">
                <AnimatePresence>
                    {toasts.map((t) => (
                        <motion.div
                            key={t.id}
                            initial={{ opacity: 0, x: 80, scale: 0.95 }}
                            animate={{ opacity: 1, x: 0, scale: 1 }}
                            exit={{ opacity: 0, x: 80, scale: 0.95 }}
                            transition={{ duration: 0.25, ease: 'easeOut' }}
                            className={`pointer-events-auto glass-strong rounded-xl border-l-4 ${borderMap[t.type]} px-4 py-3 flex items-start gap-3`}
                            role="alert"
                        >
                            <span className="flex-shrink-0 mt-0.5">{iconMap[t.type]}</span>
                            <p className="text-sm flex-1 text-slate-700 dark:text-slate-200">{t.message}</p>
                            <button
                                onClick={() => removeToast(t.id)}
                                className="flex-shrink-0 p-0.5 rounded hover:bg-slate-200/50 dark:hover:bg-slate-700/50 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
                            >
                                <X size={14} />
                            </button>
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>
        </ToastContext.Provider>
    );
}

export default ToastContext;
