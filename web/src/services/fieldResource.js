import { FIELD_AUTH_ENABLED } from '../config/runtime';
import { getFieldToken } from './fieldSession';

export async function openFieldResource(url, { downloadName = '', newTab = false } = {}) {
  const target = new URL(url, window.location.href);
  if (!FIELD_AUTH_ENABLED) {
    window.open(target.href, '_blank', 'noopener');
    return;
  }
  if (target.origin !== window.location.origin ||
      !(target.pathname.startsWith('/python/api/') || target.pathname.startsWith('/api/'))) {
    throw new Error('Resource is outside the controlled entry');
  }
  const token = getFieldToken();
  if (!token) throw new Error('Please log in again');
  const response = await fetch(target.href, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: 'omit', redirect: 'error', cache: 'no-store',
  });
  if (!response.ok) throw new Error(`Resource unavailable (${response.status})`);
  const objectUrl = URL.createObjectURL(await response.blob());
  if (newTab) {
    window.open(objectUrl, '_blank', 'noopener');
  } else {
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = downloadName || 'tracelens-result';
    anchor.click();
  }
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
}
