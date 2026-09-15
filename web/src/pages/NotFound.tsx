import { Link, useLocation } from 'react-router-dom';
import { ArrowLeft, Search } from 'lucide-react';
import BrandLogo from '../components/ui/BrandLogo';
import { useTranslation } from '../hooks/useTranslation';

/* ---------------------------------------------------------------------------
 * 品牌化 404：渲染在 Layout 主内容区内。
 * 「全局搜索」按钮通过派发 ⌘K/Ctrl+K 键盘事件唤起 CommandPalette。
 * 404 三个数字用既有 animate-rise + animationDelay 交错入场，形成轻微浮动。
 * ------------------------------------------------------------------------- */

export default function NotFound() {
  const location = useLocation();
  const { t } = useTranslation();

  const openPalette = () => {
    // CommandPalette 在 window 上监听 keydown（metaKey || ctrlKey + k）。
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'k', metaKey: true, ctrlKey: true, bubbles: true }),
    );
  };

  return (
    <div className="flex animate-rise flex-col items-center justify-center py-20 text-center lg:py-28">
      <BrandLogo size={52} className="mb-6" />

      <p aria-hidden className="select-none font-mono text-7xl font-semibold tracking-tight text-ink-900 dark:text-white">
        <span className="inline-block animate-rise">4</span>
        <span className="inline-block animate-rise text-accent-500" style={{ animationDelay: '80ms' }}>
          0
        </span>
        <span className="inline-block animate-rise" style={{ animationDelay: '160ms' }}>
          4
        </span>
      </p>

      <h1 className="mt-4 text-lg font-semibold text-ink-900 dark:text-ink-100">{t('notfound.title')}</h1>
      <p className="mt-1.5 max-w-md text-balance text-sm text-ink-500 dark:text-ink-400">
        {t('notfound.description')}
      </p>
      <p className="mt-3 inline-flex max-w-full items-center gap-1.5 rounded-md border border-ink-200 bg-ink-50 px-2.5 py-1 font-mono text-2xs text-ink-500 dark:border-ink-800 dark:bg-ink-900 dark:text-ink-400">
        <span className="shrink-0">{t('notfound.request_path')}</span>
        <span className="truncate">{location.pathname}</span>
      </p>

      <div className="mt-7 flex flex-wrap items-center justify-center gap-2.5">
        <Link to="/dashboard" className="btn-primary">
          <ArrowLeft size={15} />
          {t('notfound.back_dashboard')}
        </Link>
        <button type="button" onClick={openPalette} className="btn-secondary">
          <Search size={15} />
          {t('notfound.global_search')}
          <span className="kbd">⌘K</span>
        </button>
      </div>

      <p className="mt-5 text-2xs text-ink-400 dark:text-ink-500">
        {t('notfound.hint.prefix')} <span className="kbd">⌘K</span> {t('notfound.hint.or')}{' '}
        <span className="kbd">Ctrl</span> + <span className="kbd">K</span> {t('notfound.hint.suffix')}
      </p>
    </div>
  );
}
