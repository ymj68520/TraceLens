import { createContext, useContext, useState, useCallback, useRef } from 'react';

const ToastContext = createContext(null);

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

    const iconMap = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
    const bgMap = {
        success: 'bg-green-600',
        error: 'bg-red-600',
        info: 'bg-blue-600',
        warning: 'bg-yellow-500 text-gray-900',
    };

    return (
        <ToastContext.Provider value={toast}>
            {children}
            {/* Toast Container */}
            <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 max-w-sm">
                {toasts.map((t) => (
                    <div
                        key={t.id}
                        className={`${bgMap[t.type]} text-white px-4 py-3 rounded-lg shadow-lg flex items-start gap-3 animate-slide-in`}
                        role="alert"
                    >
                        <span className="text-lg flex-shrink-0">{iconMap[t.type]}</span>
                        <p className="text-sm flex-1">{t.message}</p>
                        <button
                            onClick={() => removeToast(t.id)}
                            className="text-white/70 hover:text-white flex-shrink-0 text-lg leading-none"
                        >
                            ×
                        </button>
                    </div>
                ))}
            </div>
            <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        .animate-slide-in { animation: slideIn 0.3s ease-out; }
      `}</style>
        </ToastContext.Provider>
    );
}

export function useToast() {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error('useToast must be used within ToastProvider');
    return ctx;
}

export default ToastContext;
