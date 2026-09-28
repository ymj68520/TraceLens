import { FIELD_AUTH_ENABLED } from '../config/runtime';
import { getFieldToken } from './fieldSession';

function controlledUrl(url) {
  const target = new URL(url, window.location.href);
  if (FIELD_AUTH_ENABLED && (target.origin !== window.location.origin ||
      !target.pathname.startsWith('/python/api/'))) {
    throw new Error('Stream is outside the controlled entry');
  }
  return target.href;
}

export async function authorizedFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (FIELD_AUTH_ENABLED) {
    const token = getFieldToken();
    if (!token) throw new Error('Please log in again');
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(controlledUrl(url), { ...options, headers, credentials: 'omit', redirect: 'error' });
}

export function openAuthenticatedEventStream(url, onMessage, onError) {
  if (!FIELD_AUTH_ENABLED) {
    const stream = new EventSource(url);
    stream.onmessage = (event) => onMessage(event.data);
    stream.onerror = (error) => onError(error);
    return { close: () => stream.close() };
  }
  const abort = new AbortController();
  (async () => {
    const response = await authorizedFetch(url, { signal: abort.signal });
    if (!response.ok || !response.body) throw new Error(`Stream unavailable (${response.status})`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    while (!abort.signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const frames = pending.split(/\r?\n\r?\n/);
      pending = frames.pop();
      for (const frame of frames) {
        const data = frame.split(/\r?\n/).filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart()).join('\n');
        if (data) onMessage(data);
      }
    }
  })().catch((error) => { if (!abort.signal.aborted) onError(error); });
  return { close: () => abort.abort() };
}
