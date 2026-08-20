/**
 * Shared helpers for the structured report sections.
 *
 * These sections mirror the reference forensic report
 * (报告_案件20260717101550_…). Even when a field has no value, it is rendered
 * as a placeholder ("—") so the report always shows the full schema.
 */

/** Render a value, falling back to an em dash when empty. */
export function val(v) {
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}

/** Format a byte count into a human-readable string. */
export function fileSize(n) {
  if (n == null || n === '') return '—';
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n);
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  if (num < 1024 * 1024 * 1024) return `${(num / 1024 / 1024).toFixed(1)} MB`;
  return `${(num / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** Format an epoch-ms or epoch-s timestamp; pass through ISO/other strings. */
export function fmtTime(t) {
  if (t === null || t === undefined || t === '') return '—';
  const num = Number(t);
  if (!Number.isFinite(num)) return String(t);
  // Heuristic: values < 1e12 are seconds, otherwise milliseconds.
  const ms = num < 1e12 ? num * 1000 : num;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return String(t);
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Format a call duration in seconds to "H时M分S秒" / "M分S秒" / "S秒". */
export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds === '') return '—';
  const s = Number(seconds);
  if (!Number.isFinite(s) || s < 0) return '—';
  if (s === 0) return '0秒';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const parts = [];
  if (h) parts.push(`${h}时`);
  if (m || h) parts.push(`${m}分`);
  parts.push(`${sec}秒`);
  return parts.join('');
}

/** Map an Android call_logs.type int to a Chinese label. */
export function callTypeLabel(type) {
  const map = { 1: '呼入电话', 2: '呼出电话', 3: '未接电话', 4: '语音邮件', 5: '拒绝', 6: '黑名单' };
  if (type === null || type === undefined || type === '') return '—';
  return map[Number(type)] || String(type);
}

/** Map an Android sms_messages.type int to a Chinese label. */
export function smsTypeLabel(type) {
  const map = { 1: '接收', 2: '发送', 3: '草稿', 4: '发件箱', 5: '发送失败', 6: '已发送' };
  if (type === null || type === undefined || type === '') return '—';
  return map[Number(type)] || String(type);
}

/** A definition-list pair (label → value), always rendered even when empty. */
export function Field({ label, children, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={`break-words text-slate-800 dark:text-slate-100 ${mono ? 'font-mono text-[12px]' : 'text-sm'}`}>
        {children}
      </dd>
    </div>
  );
}

/** Card wrapper used by all sections for visual consistency. */
export function SectionCard({ title, total, onEdit, children, action }) {
  return (
    <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-bold text-slate-900 dark:text-white">
          {title}
          {typeof total === 'number' && (
            <span className="ml-2 text-xs font-normal text-slate-500 dark:text-slate-400">
              （共 {total} 条）
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          {action}
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              className="text-xs font-semibold px-2.5 py-1 rounded-lg border border-primary-300 text-primary-700 bg-primary-50 hover:bg-primary-100 dark:bg-primary-900/30 dark:text-primary-300 dark:border-primary-700"
            >
              ✎ 编辑
            </button>
          )}
        </div>
      </div>
      {children}
    </section>
  );
}

/** Empty-state placeholder shown when a section has zero records. */
export function EmptySection({ text = '该分类暂无记录。' }) {
  return (
    <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 dark:border-slate-600 dark:text-slate-500">
      {text}
    </p>
  );
}

/** Small status badge. */
export function Badge({ children, className = '' }) {
  return <span className={`inline-block px-1.5 py-0.5 text-[10px] font-semibold rounded ${className}`}>{children}</span>;
}
