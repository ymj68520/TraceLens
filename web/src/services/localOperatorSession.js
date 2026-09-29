import { LOCAL_AUTO_SESSION_ENABLED, isLocalOperatorOrigin } from '../config/runtime';

let pending;

// No user password or service credential is shipped to the browser. The exact
// loopback gateway POST uses a private, separately named local operator account.
export function getLocalOperatorSession() {
  if (!LOCAL_AUTO_SESSION_ENABLED || !isLocalOperatorOrigin(window.location.origin)) {
    return Promise.reject(new Error('local operator entry is unavailable'));
  }
  if (!pending) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    pending = fetch('/_local/session', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error('local operator entry is unavailable');
      const session = await response.json();
      if (!session.access_token || session.token_type !== 'bearer'
          || session.principal?.id !== 'local-auto-operator' || session.principal?.role !== 'admin') {
        throw new Error('invalid local operator session');
      }
      return session;
    }).finally(() => { clearTimeout(timeout); pending = undefined; });
  }
  return pending;
}

export function localReturnPath(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    && !value.includes('\\') && !value.startsWith('/login') && !value.startsWith('/_local')
    ? value : '/dashboard';
}
