import { useState, type FormEvent } from 'react';
import { Server, LogIn, LogOut } from 'lucide-react';
import { csLogin, csMe, listClients } from '../services/csService';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import { errorMessage } from '../lib/utils';

/** Distributed C/S smoke page — proves the browser can reach :8091 end-to-end. */
export default function Distributed() {
  const [username, setUsername] = useState('super_admin');
  const [password, setPassword] = useState('admin123');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const tokenResp = (await csLogin(username, password)) as { access_token?: string; token_type?: string; expires_in?: number };
      const token = tokenResp?.access_token;
      if (!token) throw new Error(`登录响应缺少 access_token: ${JSON.stringify(tokenResp)}`);
      localStorage.setItem('cs_auth_token', token);

      const [clients, me] = await Promise.all([
        listClients().catch((err) => ({ __error: String(err), __stage: 'listClients' })),
        csMe().catch((err) => ({ __error: String(err), __stage: 'csMe' })),
      ]);
      setResult({ token_type: tokenResp.token_type, expires_in: tokenResp.expires_in, me, clients });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('cs_auth_token');
    setResult(null);
    setError(null);
  };

  const loggedIn = Boolean(typeof window !== 'undefined' && localStorage.getItem('cs_auth_token'));

  return (
    <div className="space-y-4 max-w-3xl">
      <Card>
        <CardHeader
          title="分布式 C/S 服务连通性"
          subtitle="通过 Vite 代理访问 :8091 — 登录 → 保存 token → 请求 /api/clients"
        />
        <form onSubmit={handleLogin} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label" htmlFor="cs-user">用户名</label>
              <input
                id="cs-user"
                type="text"
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </div>
            <div>
              <label className="field-label" htmlFor="cs-pass">密码</label>
              <input
                id="cs-pass"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="primary" type="submit" disabled={busy}>
              <LogIn size={14} />
              {busy ? '登录中…' : '登录并拉取节点'}
            </Button>
            {loggedIn && (
              <Button variant="ghost" onClick={handleLogout}>
                <LogOut size={14} /> 清除凭据
              </Button>
            )}
            <span className="text-2xs text-ink-400 inline-flex items-center gap-1">
              <Server size={12} />
              状态：{loggedIn ? '已持有 cs_auth_token' : '未登录'}
            </span>
          </div>
        </form>
      </Card>

      {error && (
        <Card>
          <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader title="响应" />
          <pre className="code-block max-h-[420px] overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
