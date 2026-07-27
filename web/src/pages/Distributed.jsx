import { useState } from 'react';
import { csLogin, csMe } from '../services/csAuthService';
import { listClients } from '../services/csClientService';

// Minimal smoke page proving the distributed C/S server (:8091) is reachable
// end-to-end from the browser via the /csapi Vite proxy. NOT polished — scope is
// a real browser fetch through the proxy that renders data (not a CORS error).
const Distributed = () => {
  const [username, setUsername] = useState('super_admin');
  const [password, setPassword] = useState('admin123');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleLogin = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // csLogin returns response.data (the response interceptor unwraps it).
      // TokenResponse shape: { access_token, token_type, expires_in }.
      const tokenResp = await csLogin(username, password);
      const token = tokenResp?.access_token;
      if (!token) {
        throw new Error(`No access_token in login response: ${JSON.stringify(tokenResp)}`);
      }
      localStorage.setItem('cs_auth_token', token);

      // Authenticated round-trip: fetch clients list + /me for good measure.
      const [clients, me] = await Promise.all([
        listClients().catch((err) => ({ __error: err, __stage: 'listClients' })),
        csMe().catch((err) => ({ __error: err, __stage: 'csMe' })),
      ]);
      setResult({ token_type: tokenResp.token_type, expires_in: tokenResp.expires_in, me, clients });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const handleClear = () => {
    localStorage.removeItem('cs_auth_token');
    setResult(null);
    setError(null);
  };

  return (
    <div style={{ padding: 24, fontFamily: 'monospace', maxWidth: 900 }}>
      <h2 style={{ marginTop: 0 }}>Distributed C/S smoke test (:8091)</h2>
      <p style={{ color: '#64748b' }}>
        Proves the browser can reach the distributed server through the <code>/csapi</code> Vite proxy
        (login &#8594; store <code>access_token</code> &#8594; authenticated <code>/api/clients</code>).
      </p>

      <form onSubmit={handleLogin} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="username"
          style={{ padding: 6, fontFamily: 'monospace' }}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          style={{ padding: 6, fontFamily: 'monospace' }}
        />
        <button type="submit" disabled={busy} style={{ padding: '6px 12px' }}>
          {busy ? 'Working...' : 'Login & fetch clients'}
        </button>
        <button type="button" onClick={handleClear} style={{ padding: '6px 12px' }}>
          Clear token
        </button>
      </form>

      {error && (
        <div style={{ background: '#fee2e2', padding: 12, border: '1px solid #ef4444', whiteSpace: 'pre-wrap', marginBottom: 12 }}>
          <strong>Error:</strong> {JSON.stringify(error, null, 2)}
        </div>
      )}

      {result && (
        <div style={{ background: '#f1f5f9', padding: 12, border: '1px solid #cbd5e1', whiteSpace: 'pre-wrap' }}>
          <strong>OK — token_type:</strong> {String(result.token_type)}{' '}
          | <strong>expires_in:</strong> {String(result.expires_in)}s
          <hr style={{ margin: '8px 0' }} />
          <strong>/api/auth/me:</strong>
          <pre style={{ margin: 0 }}>{JSON.stringify(result.me, null, 2)}</pre>
          <hr style={{ margin: '8px 0' }} />
          <strong>/api/clients:</strong>
          <pre style={{ margin: 0 }}>{JSON.stringify(result.clients, null, 2)}</pre>
        </div>
      )}
    </div>
  );
};

export default Distributed;
