import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { Menu, X, PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react';
import { useAppSelector } from '../../store';
import TaskSelector from '../tasks/TaskSelector';
import NotificationCenter from '../notifications/NotificationCenter';
import ShortcutsDialog from '../shortcuts/ShortcutsDialog';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';
import BrandLogo from '../ui/BrandLogo';
import Tooltip, { TooltipProvider } from '../ui/Tooltip';
import CommandPalette from './CommandPalette';
import { buildNavSections, TASK_CONTEXT_PAGES, NAV_GROUP_LABELS } from './navConfig';
import { useTranslation } from '../../hooks/useTranslation';
import { cx } from '../../lib/utils';

const COLLAPSE_KEY = 'sidebar.collapsed';

export default function Layout({ children }: { children: ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  useKeyboardShortcuts({ onOpenHelp: () => setShortcutsOpen(true) });
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const currentTaskId = searchParams.get('task_id');
  const showTerminal = useAppSelector((state) => state.settings.showTerminal);
  const runningCount = useAppSelector((state) => state.tasks.tasks.filter((t) => t.status === 'running').length);
  const { t } = useTranslation();

  const userName = localStorage.getItem('auth_user') || '分析员';
  const userInitials = userName.slice(0, 2).toUpperCase();

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
  }, [collapsed]);

  const navSections = buildNavSections(showTerminal);

  const isActive = (path: string) => location.pathname === path;

  const withTaskContext = (href: string) =>
    currentTaskId && TASK_CONTEXT_PAGES.has(href) ? `${href}?task_id=${currentTaskId}` : href;

  const activeTitle =
    navSections
      .flatMap((s) => s.items)
      .find((item) => isActive(item.href))?.key ?? 'nav.dashboard';

  const renderItem = (item: { key: string; href: string; icon: typeof Search }) => {
    const Icon = item.icon;
    const active = isActive(item.href);
    const link = (
      <Link
        to={withTaskContext(item.href)}
        title={collapsed ? t(item.key) : undefined}
        aria-current={active ? 'page' : undefined}
        className={cx(
          'group relative flex items-center gap-2.5 rounded-md text-[13px] font-medium transition-all duration-100',
          collapsed ? 'justify-center px-0 py-2' : 'px-3 py-[7px]',
          active
            ? 'bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300'
            : 'text-ink-600 dark:text-ink-400 hover:text-ink-900 dark:hover:text-ink-100 hover:bg-ink-100/80 dark:hover:bg-white/5',
        )}
        onClick={() => setMobileMenuOpen(false)}
      >
        {active && (
          <span aria-hidden className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent-500" />
        )}
        <Icon
          size={16}
          strokeWidth={active ? 2 : 1.75}
          className={cx(
            'shrink-0 transition-colors',
            active ? 'text-accent-600 dark:text-accent-400' : 'text-ink-400 dark:text-ink-500 group-hover:text-ink-600 dark:group-hover:text-ink-300',
          )}
        />
        {!collapsed && <span className="truncate">{t(item.key)}</span>}
      </Link>
    );
    // Collapsed rail: reveal the label through a tooltip instead of truncation.
    return (
      <li key={item.href}>
        {collapsed ? (
          <Tooltip content={t(item.key)} side="right">
            {link}
          </Tooltip>
        ) : (
          link
        )}
      </li>
    );
  };

  return (
    <TooltipProvider>
      <div className="min-h-screen">
      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 inset-x-0 z-50 bg-white dark:bg-ink-925 border-b border-ink-200 dark:border-ink-800 px-4 py-3 flex items-center">
        <button
          type="button"
          className="p-2 rounded-md text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span className="sr-only">打开侧边栏</span>
          {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <h1 className="ml-3 text-base font-semibold text-ink-900 dark:text-white tracking-tight">
          {t('app.title')}
        </h1>
      </div>

      {/* Sidebar */}
      <aside
        className={cx(
          'fixed inset-y-0 left-0 z-40 transition-all duration-200 ease-in-out',
          collapsed ? 'lg:w-14' : 'lg:w-60',
          mobileMenuOpen ? 'translate-x-0 w-60' : '-translate-x-full lg:translate-x-0',
        )}
      >
        <div className="flex flex-col h-full bg-white dark:bg-ink-925 border-r border-ink-200/80 dark:border-ink-800">
          {/* Brand */}
          <div className="hidden lg:flex items-center h-14 px-4 border-b border-ink-200/70 dark:border-ink-800/60 shrink-0">
            <div className={cx('flex items-center min-w-0', collapsed ? 'mx-auto' : 'gap-2.5')}>
              <BrandLogo size={28} className="shrink-0" />
              {!collapsed && (
                <span className="text-sm font-semibold text-ink-900 dark:text-white tracking-tight truncate">
                  {t('app.title')}
                </span>
              )}
            </div>
          </div>

          {/* Nav — grouped sections with micro-caps labels */}
          <nav className="flex-1 overflow-y-auto px-2 py-3 pt-16 lg:pt-3">
            {navSections.map((section, si) => (
              <div key={section.label} className={cx(si > 0 && 'mt-4')}>
                {!collapsed && <p className="section-label px-3 pb-1">{NAV_GROUP_LABELS[section.label]}</p>}
                <ul className="space-y-0.5">{section.items.map(renderItem)}</ul>
              </div>
            ))}
          </nav>

          {/* User card + collapse toggle */}
          <div className="hidden lg:block border-t border-ink-200/70 dark:border-ink-800/60 p-2 shrink-0">
            {!collapsed ? (
              <div className="mb-1 flex items-center gap-2.5 rounded-md bg-ink-50 dark:bg-white/5 px-2 py-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-100 dark:bg-accent-500/15 text-2xs font-semibold text-accent-700 dark:text-accent-300">
                  {userInitials}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-ink-800 dark:text-ink-200">{userName}</span>
                  <span className="block text-2xs text-ink-400 dark:text-ink-500">本地模式</span>
                </span>
              </div>
            ) : (
              <Tooltip content={userName} side="right">
                <div className="mx-auto mb-1 flex h-7 w-7 items-center justify-center rounded-full bg-accent-100 dark:bg-accent-500/15 text-2xs font-semibold text-accent-700 dark:text-accent-300">
                  {userInitials}
                </div>
              </Tooltip>
            )}
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              className="w-full flex items-center justify-center gap-2 px-2 py-1.5 text-xs font-medium text-ink-400 hover:text-ink-700 dark:hover:text-ink-200 rounded-md hover:bg-ink-100/80 dark:hover:bg-white/5 transition-colors"
            >
              {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
              {!collapsed && t('sidebar.collapse')}
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className={cx('pt-14 lg:pt-0 transition-all duration-200', collapsed ? 'lg:pl-14' : 'lg:pl-60')}>
        {/* Header — solid surface; running-tasks indicator is real store data */}
        <header className="sticky top-0 z-30 h-14 bg-white dark:bg-ink-925 border-b border-ink-200 dark:border-ink-800 px-5 flex items-center">
          <div className="flex items-center justify-between gap-4 w-full">
            <h2 className="text-base font-semibold text-ink-900 dark:text-white tracking-tight">
              {t(activeTitle)}
            </h2>
            <div className="flex items-center gap-2.5">
              <NotificationCenter />
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="hidden sm:inline-flex items-center gap-2 rounded-md border border-ink-200 dark:border-ink-700 bg-ink-50 dark:bg-ink-900 px-2.5 py-1.5 text-xs text-ink-400 dark:text-ink-500 hover:border-ink-300 dark:hover:border-ink-600 hover:text-ink-600 dark:hover:text-ink-300 transition-colors"
              >
                <Search size={13} />
                <span>搜索</span>
                <span className="kbd">⌘K</span>
              </button>
              {runningCount > 0 && (
                <Link
                  to="/tasks"
                  className="inline-flex items-center gap-1.5 text-xs text-ink-500 dark:text-ink-400 hover:text-ink-700 dark:hover:text-ink-200 transition-colors"
                >
                  <span className="dot-run" />
                  {runningCount} 个任务运行中
                </Link>
              )}
              <TaskSelector />
            </div>
          </div>
        </header>

        <main className="p-5 lg:p-7">
          {/* Re-keying on route change replays the entrance animation per page. */}
          <div key={location.pathname} className="animate-rise">
            {children}
          </div>
        </main>
      </div>

      {/* Mobile scrim */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink-950/50 lg:hidden animate-fade-in"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      </div>
    </TooltipProvider>
  );
}
