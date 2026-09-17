// FileEventsDrawer.jsx
// Slide-in drawer behind a report's file tag (mvp-phase1-acceptance SPEC §6.2):
// shows the file identity plus the RAW timeline events referencing it — no LLM
// involved — and an "index file" jump to the Files page.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { Clock, ExternalLink, FileText, X } from 'lucide-react';
import Spinner from '../common/Spinner';
import { getFileEvents } from '../../services/associationService';

const formatEventTime = (value) => {
  const n = Number(value);
  if (!n) return '—';
  const date = new Date(n * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};

const EVENT_TYPE_COLOR = {
  CREATED: 'text-emerald-700 dark:text-emerald-300',
  MODIFIED: 'text-blue-700 dark:text-blue-300',
  ACCESSED: 'text-amber-700 dark:text-amber-300',
  CHANGED: 'text-purple-700 dark:text-purple-300',
  DELETED: 'text-rose-700 dark:text-rose-300',
};

export default function FileEventsDrawer({ taskId, filePath, onClose }) {
  const [events, setEvents] = useState(null);
  const [matchedBy, setMatchedBy] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!taskId || !filePath) return undefined;
    let alive = true;
    setLoading(true);
    setError(null);
    setEvents(null);
    getFileEvents(taskId, filePath, 200)
      .then((payload) => {
        if (!alive) return;
        setEvents(payload?.events || []);
        setMatchedBy(payload?.matched_by || null);
      })
      .catch((err) => {
        if (alive) setError(err);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [taskId, filePath]);

  const basename = String(filePath || '').split('/').pop() || filePath;

  return (
    <AnimatePresence>
      {filePath && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-slate-900/30 backdrop-blur-[2px] z-40"
            onClick={onClose}
            data-testid="file-events-drawer-backdrop"
          />
          <motion.aside
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed top-0 right-0 bottom-0 w-full lg:w-[520px] bg-white dark:bg-slate-900 shadow-2xl z-50 border-l border-slate-200 dark:border-slate-700 flex flex-col"
            data-testid="file-events-drawer"
            aria-label="File related events"
          >
            <div className="p-4 border-b border-slate-100 dark:border-slate-800 flex justify-between items-start bg-slate-50/60 dark:bg-slate-800/40">
              <div className="min-w-0">
                <h3 className="text-sm font-black text-slate-900 dark:text-white uppercase tracking-tighter flex items-center">
                  <FileText className="w-4 h-4 mr-2 text-primary-500" /> 文件与相关事件
                </h3>
                <p className="mt-1 text-xs font-mono text-slate-500 break-all">{filePath}</p>
              </div>
              <div className="flex items-center gap-1 pl-2">
                <Link
                  to={`/files?task_id=${encodeURIComponent(taskId || '')}`}
                  title="在文件页中索引该文件"
                  className="p-2 rounded-full text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/30 transition-colors"
                  data-testid="file-events-index-link"
                >
                  <ExternalLink size={16} />
                </Link>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close file events drawer"
                  className="p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {loading && <div className="flex justify-center py-10"><Spinner size="lg" /></div>}
              {!loading && error && (
                <div className="rounded-xl border border-rose-300 bg-rose-50 dark:bg-rose-950/20 p-4 text-sm text-rose-700 dark:text-rose-300" role="alert">
                  相关事件加载失败：{error.message || error}
                </div>
              )}
              {!loading && !error && Array.isArray(events) && events.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-6 text-center text-sm text-slate-500 dark:text-slate-400">
                  时间线中没有引用该文件的事件。
                </div>
              )}
              {!loading && !error && events?.length > 0 && (
                <>
                  <p className="text-[11px] text-slate-400" data-testid="file-events-matched-by">
                    共 {events.length} 条事件{matchedBy === 'basename' ? '（按文件名匹配）' : ''} · 原始时间线记录，未经 LLM 分析
                  </p>
                  {events.map((event, index) => (
                    <div
                      key={event.id ?? index}
                      className="rounded-xl border border-slate-200/70 dark:border-slate-700/70 p-3"
                      data-testid="file-event-row"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className={`text-xs font-bold ${EVENT_TYPE_COLOR[event.event_type] || 'text-slate-700 dark:text-slate-200'}`}>
                          {event.event_type || 'EVENT'}
                        </span>
                        <span className="text-xs text-slate-500 flex items-center gap-1">
                          <Clock size={12} /> {formatEventTime(event.timestamp)}
                        </span>
                      </div>
                      {event.description && (
                        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 break-words">{event.description}</p>
                      )}
                      {event.file_path && event.file_path !== filePath && (
                        <p className="mt-1 text-[11px] text-slate-400 font-mono break-all">{event.file_path}</p>
                      )}
                    </div>
                  ))}
                </>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
