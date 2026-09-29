// Browser-facing service configuration.
// Vite only exposes VITE_* variables to client code. In production, the C++
// service is normally the page origin; Python and C/S remain explicit origins.

const env = import.meta.env || {};
export const FIELD_AUTH_ENABLED = env.VITE_FIELD_AUTH === 'enabled';
// Explicit, temporary loopback UI profile. Backend authentication stays enabled.
export const LOCAL_AUTO_SESSION_ENABLED = FIELD_AUTH_ENABLED && env.VITE_LOCAL_AUTO_SESSION === 'enabled';

export function isLocalOperatorOrigin(origin) {
  try {
    const parsed = new URL(origin);
    return parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname)
      && parsed.port === '8666' && !parsed.username && !parsed.password;
  } catch {
    return false;
  }
}

function pageOrigin() {
  if (typeof window === 'undefined' || !window.location) return 'http://localhost';
  return window.location.origin;
}

function pageEndpoint(port) {
  if (typeof window === 'undefined' || !window.location) {
    return `http://localhost:${port}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return `${protocol}//${window.location.hostname}:${port}`;
}

export const API_BASE_URL = FIELD_AUTH_ENABLED ? '' : (env.VITE_API_BASE_URL || '');
export const CPP_BASE_URL = FIELD_AUTH_ENABLED ? pageOrigin() : (env.VITE_CPP_API_URL
  || (env.VITE_CPP_PORT ? pageEndpoint(env.VITE_CPP_PORT) : pageOrigin()));
// A missing build setting must never discover a previously running 8090/8091
// service on the operator's machine. Legacy direct-port development requires
// an explicit VITE_* URL; release/test builds use the controlled same-origin
// gateway. /cs-disabled is deliberately not a live service route.
export const PYTHON_API_BASE_URL = FIELD_AUTH_ENABLED ? '/python' : (env.VITE_PYTHON_API_URL || '/python');
export const CS_API_BASE_URL = FIELD_AUTH_ENABLED ? '/cs-disabled' : (env.VITE_CS_API_URL || '/cs-disabled');

export const CPP_WS_BASE_URL = FIELD_AUTH_ENABLED
  ? CPP_BASE_URL.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
  : (env.VITE_CPP_WS_URL || CPP_BASE_URL.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:'));

export const SERVICE_TIMEOUTS = {
  cpp: Number(env.VITE_CPP_TIMEOUT_MS || 30000),
  python: Number(env.VITE_PYTHON_TIMEOUT_MS || 120000),
  cs: Number(env.VITE_CS_TIMEOUT_MS || 30000),
};

export const SERVICE_PORTS = {
  cpp: env.VITE_CPP_PORT || '',
  python: env.VITE_PYTHON_PORT || '',
  cs: env.VITE_CS_PORT || '',
};
// Baked by the isolated field build; never use a disk HEAD as process identity.
export const FIELD_RELEASE_ID = import.meta.env.VITE_FIELD_RELEASE_ID || 'UNFROZEN_WORKTREE';
