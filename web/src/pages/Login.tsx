import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, User, ArrowRight, Database, Network, FileSearch } from 'lucide-react';
import BrandLogo from '../components/ui/BrandLogo';
import { useTranslation } from '../hooks/useTranslation';

/* 特性列表文案走 login.feature.* 键；图标与键在此配对 */
const FEATURES = [
  { Icon: Database, titleKey: 'login.feature.extraction.title', descKey: 'login.feature.extraction.desc' },
  { Icon: Network, titleKey: 'login.feature.graph.title', descKey: 'login.feature.graph.desc' },
  { Icon: FileSearch, titleKey: 'login.feature.ai.title', descKey: 'login.feature.ai.desc' },
] as const;

export default function Login() {
  const navigate = useNavigate();
  const { t } = useTranslation();
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
        setError(t('login.error.required'));
      }
    } catch {
      setError(t('login.error.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.1fr_1fr] bg-white dark:bg-ink-925">
      {/* Brand panel — desktop only, light with an accent wash */}
      <div className="relative hidden lg:flex flex-col justify-between p-10 overflow-hidden bg-gradient-to-br from-accent-50 via-white to-ink-100 dark:from-ink-950 dark:via-ink-925 dark:to-ink-950">
        {/* Hairline grid texture in accent tone */}
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.35] dark:opacity-[0.05]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(13,138,137,0.16) 1px, transparent 1px), linear-gradient(90deg, rgba(13,138,137,0.16) 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />
        <div className="relative flex items-center gap-2.5 animate-rise">
          <BrandLogo size={32} />
          <span className="text-sm font-semibold tracking-tight text-ink-900 dark:text-white">TraceLens</span>
        </div>

        <div className="relative max-w-md">
          <h1 className="text-3xl font-semibold leading-snug tracking-tight text-ink-900 dark:text-white animate-rise" style={{ animationDelay: '60ms' }}>
            {t('login.slogan.line1')}
            <br />
            {t('login.slogan.line2')}
          </h1>
          <ul className="mt-10 space-y-6">
            {FEATURES.map(({ Icon, titleKey, descKey }, i) => (
              <li
                key={titleKey}
                className="flex items-start gap-3.5 animate-rise"
                style={{ animationDelay: `${120 + i * 70}ms` }}
              >
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-accent-200/70 bg-white/80 dark:border-ink-700 dark:bg-ink-900 text-accent-600 dark:text-accent-400 shadow-sm transition hover:-translate-y-0.5">
                  <Icon size={15} strokeWidth={1.75} />
                </span>
                <span>
                  <span className="block text-sm font-medium text-ink-800 dark:text-ink-100">
                    <span className="mr-2 font-mono text-2xs text-accent-600/70 dark:text-accent-500/70">0{i + 1}</span>
                    {t(titleKey)}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-500 dark:text-ink-400">{t(descKey)}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative font-mono text-2xs text-ink-400 dark:text-ink-600 animate-rise" style={{ animationDelay: '340ms' }}>
          {t('login.version_footer')}
        </p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          {/* Compact brand for mobile; logo scales up from sm via className overrides */}
          <div className="mb-8 text-center lg:hidden animate-rise">
            <div className="mb-3 flex justify-center">
              <BrandLogo size={44} className="h-10 w-10 sm:h-14 sm:w-14" />
            </div>
            <h1 className="text-lg font-semibold tracking-tight text-ink-900 dark:text-white">TraceLens</h1>
            <p className="mt-0.5 text-sm text-ink-500 dark:text-ink-400">{t('login.tagline')}</p>
          </div>

          <div className="mb-6 hidden lg:block animate-rise" style={{ animationDelay: '80ms' }}>
            <h2 className="text-xl font-semibold tracking-tight text-ink-900 dark:text-white">{t('login.title')}</h2>
            <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">{t('login.subtitle')}</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4 animate-rise" style={{ animationDelay: '160ms' }}>
            <div>
              <label htmlFor="login-username" className="field-label">
                {t('login.username_label')}
              </label>
              <div className="relative">
                <User size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <input
                  id="login-username"
                  type="text"
                  value={credentials.username}
                  onChange={(e) => setCredentials({ ...credentials, username: e.target.value })}
                  className="input pl-9"
                  placeholder={t('login.username_placeholder')}
                  autoComplete="username"
                  disabled={loading}
                />
              </div>
            </div>

            <div>
              <label htmlFor="login-password" className="field-label">
                {t('login.password_label')}
              </label>
              <div className="relative">
                <Lock size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <input
                  id="login-password"
                  type="password"
                  value={credentials.password}
                  onChange={(e) => setCredentials({ ...credentials, password: e.target.value })}
                  className="input pl-9"
                  placeholder={t('login.password_placeholder')}
                  autoComplete="current-password"
                  disabled={loading}
                />
              </div>
            </div>

            {error && (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-400 animate-fade-in">
                {error}
              </p>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
              {loading ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <>
                  {t('login.submit')} <ArrowRight size={15} />
                </>
              )}
            </button>
          </form>

          <p className="mt-4 text-center text-2xs text-ink-400 dark:text-ink-600 animate-rise" style={{ animationDelay: '240ms' }}>
            {t('login.demo_hint')}
          </p>
        </div>
      </div>
    </div>
  );
}
