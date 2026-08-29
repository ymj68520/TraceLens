import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, User, ArrowRight, ScanSearch } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const [credentials, setCredentials] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await new Promise((r) => setTimeout(r, 400));
      if (credentials.username && credentials.password) {
        localStorage.setItem('auth_token', `mock_jwt_token_${Date.now()}`);
        localStorage.setItem('auth_user', credentials.username);
        navigate('/dashboard');
      } else {
        setError('请输入用户名和密码');
      }
    } catch {
      setError('登录失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-lg bg-accent-600 mb-4">
            <ScanSearch size={22} className="text-white" />
          </div>
          <h1 className="text-xl font-semibold text-white tracking-tight">TraceLens</h1>
          <p className="mt-1 text-sm text-ink-500">数字取证分析平台</p>
        </div>

        <div className="bg-ink-925 border border-ink-800 rounded-lg p-6 shadow-pop">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="login-username" className="block text-xs font-medium text-ink-400 mb-1.5">
                用户名
              </label>
              <div className="relative">
                <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
                <input
                  id="login-username"
                  type="text"
                  value={credentials.username}
                  onChange={(e) => setCredentials({ ...credentials, username: e.target.value })}
                  className="input pl-9 bg-ink-900 border-ink-700 text-ink-100"
                  placeholder="输入用户名"
                  autoComplete="username"
                />
              </div>
            </div>

            <div>
              <label htmlFor="login-password" className="block text-xs font-medium text-ink-400 mb-1.5">
                密码
              </label>
              <div className="relative">
                <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
                <input
                  id="login-password"
                  type="password"
                  value={credentials.password}
                  onChange={(e) => setCredentials({ ...credentials, password: e.target.value })}
                  className="input pl-9 bg-ink-900 border-ink-700 text-ink-100"
                  placeholder="输入密码"
                  autoComplete="current-password"
                />
              </div>
            </div>

            {error && (
              <p className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 px-3 py-2 rounded-md">
                {error}
              </p>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
              {loading ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  登录 <ArrowRight size={15} />
                </>
              )}
            </button>
          </form>

          <p className="mt-4 text-center text-2xs text-ink-600">演示环境：任意用户名和密码均可登录</p>
        </div>
      </div>
    </div>
  );
}
