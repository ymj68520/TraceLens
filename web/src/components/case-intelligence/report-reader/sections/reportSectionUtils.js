/**
 * Pure formatting helpers for structured report sections.
 */

export function val(v) {
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}

export function fileSize(n) {
  if (n == null || n === '') return '—';
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n);
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  if (num < 1024 * 1024 * 1024) return `${(num / 1024 / 1024).toFixed(1)} MB`;
  return `${(num / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtTime(t) {
  if (t === null || t === undefined || t === '') return '—';
  const num = Number(t);
  if (!Number.isFinite(num)) return String(t);
  const ms = num < 1e12 ? num * 1000 : num;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return String(t);
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

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

export function callTypeLabel(type) {
  const map = { 1: '呼入电话', 2: '呼出电话', 3: '未接电话', 4: '语音邮件', 5: '拒绝', 6: '黑名单' };
  if (type === null || type === undefined || type === '') return '—';
  return map[Number(type)] || String(type);
}

export function smsTypeLabel(type) {
  const map = { 1: '接收', 2: '发送', 3: '草稿', 4: '发件箱', 5: '发送失败', 6: '已发送' };
  if (type === null || type === undefined || type === '') return '—';
  return map[Number(type)] || String(type);
}
