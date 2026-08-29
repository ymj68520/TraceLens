import { useState, type ReactNode } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import {
  LayoutDashboard,
  ListTodo,
  Clock,
  FolderOpen,
  Network,
  FileSearch,
  Smartphone,
  Cloud,
  Search,
  BarChart3,
  Settings,
  Menu,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  FileText,
  Briefcase,
  MessageCircle,
  Cpu,
  ScanSearch,
  Share2,
  Server,
} from 'lucide-react';
import { useAppSelector } from '../../store';
import TaskSelector from '../tasks/TaskSelector';
import { useTranslation } from '../../hooks/useTranslation';
import { cx } from '../../lib/utils';

interface NavItem {
  key: string;
  href: string;
  icon: typeof LayoutDashboard;
  hardcoded?: string;
}

/** Pages that keep the current task context in the URL across navigation. */
const TASK_CONTEXT_PAGES = new Set([
  '/timeline',
  '/files',
  '/case-intelligence',
  '/analysis-center',
  '/knowledge-graph',
  '/investigation-graph',
  '/investigation',
  '/android',
  '/memory',
  '/wechat-graph',
  '/oss',
  '/search',
  '/statistics',
]);

export default function Layout({ children }: { children: ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const currentTaskId = searchParams.get('task_id');
  const showTerminal = useAppSelector((state) => state.settings.showTerminal);
  const { t } = useTranslation();

  const navigation: NavItem[] = [
    { key: 'nav.dashboard', href: '/dashboard', icon: LayoutDashboard },
    { key: 'nav.tasks', href: '/tasks', icon: ListTodo },
    { key: 'nav.cases', href: '/cases', icon: Briefcase },
    { key: 'nav.timeline', href: '/timeline', icon: Clock },
    { key: 'nav.files', href: '/files', icon: FolderOpen },
    { key: 'nav.case_intelligence', href: '/case-intelligence', icon: FileText },
    { key: 'nav.case_center', href: '/analysis-center', icon: ScanSearch },
    { key: 'nav.knowledge_graph', href: '/knowledge-graph', icon: Network },
    { key: 'nav.investigation_workbench', href: '/investigation', icon: FileSearch },
    { key: 'nav.android', href: '/android', icon: Smartphone },
    { key: 'nav.memory', href: '/memory', icon: Cpu },
    { key: 'nav.wechat_graph', href: '/wechat-graph', icon: MessageCircle },
    { key: 'nav.oss_analysis', href: '/oss', icon: Cloud },
    { key: 'nav.search', href: '/search', icon: Search },
    { key: 'nav.statistics', href: '/statistics', icon: BarChart3 },
    { key: 'nav.distributed', href: '/distributed', icon: Server },
  ];

  if (showTerminal) {
    navigation.push({ key: 'nav.terminal', href: '/terminal', icon: Share2 });
  }

  navigation.push({ key: 'nav.settings', href: '/settings', icon: Settings });

  const isActive = (path: string) => location.pathname === path;

  const withTaskContext = (href: string) =>
    currentTaskId && TASK_CONTEXT_PAGES.has(href) ? `${href}?task_id=${currentTaskId}` : href;

  const activeTitle =
    navigation.find((item) => isActive(item.href))?.key ?? 'nav.dashboard';

  return (
    <div className="min-h-screen">
      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 inset-x-0 z-50 bg-white dark:bg-ink-925 border-b border-ink-200 dark:border-ink-800 px-4 py-3 flex items-center">
        <button
          type="button"
          className="p-2 rounded-md text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span className="sr-only">Open sidebar</span>
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
          collapsed ? 'lg:w-16' : 'lg:w-60',
          mobileMenuOpen ? 'translate-x-0 w-60' : '-translate-x-full lg:translate-x-0',
        )}
      >
        <div className="flex flex-col h-full bg-ink-950 border-r border-ink-800/60">
          {/* Brand */}
          <div className="hidden lg:flex items-center h-14 px-4 border-b border-ink-800/60">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-7 h-7 rounded-md bg-accent-600 flex items-center justify-center shrink-0">
                <ScanSearch size={15} className="text-white" />
              </div>
              {!collapsed && (
                <span className="text-sm font-semibold text-white tracking-tight truncate">
                  {t('app.title')}
                </span>
              )}
            </div>
          </div>

          {/* Nav */}
          <nav className="flex-1 overflow-y-auto px-2 py-3 pt-16 lg:pt-3">
            <ul className="space-y-0.5">
              {navigation.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      to={withTaskContext(item.href)}
                      title={collapsed ? t(item.key) : undefined}
                      className={cx(
                        'group flex items-center gap-2.5 rounded-md text-[13px] font-medium transition-colors',
                        collapsed ? 'justify-center px-0 py-2' : 'px-3 py-2',
                        active
                          ? 'bg-accent-600/15 text-accent-300'
                          : 'text-ink-400 hover:text-ink-100 hover:bg-white/5',
                      )}
                      onClick={() => setMobileMenuOpen(false)}
                    >
                      <Icon
                        size={17}
                        className={cx(
                          'shrink-0 transition-colors',
                          active ? 'text-accent-400' : 'text-ink-500 group-hover:text-ink-300',
                        )}
                      />
                      {!collapsed && <span className="truncate">{t(item.key)}</span>}
                      {active && !collapsed && (
                        <span className="ml-auto w-1 h-4 rounded-full bg-accent-500" />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Collapse toggle */}
          <div className="hidden lg:block border-t border-ink-800/60 p-2">
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              className="w-full flex items-center justify-center gap-2 px-2 py-1.5 text-xs font-medium text-ink-500 hover:text-ink-200 rounded-md hover:bg-white/5 transition-colors"
            >
              {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
              {!collapsed && t('sidebar.collapse')}
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className={cx('pt-14 lg:pt-0 transition-all duration-200', collapsed ? 'lg:pl-16' : 'lg:pl-60')}>
        {/* Header */}
        <header className="sticky top-0 z-30 bg-white/95 dark:bg-ink-925/95 backdrop-blur border-b border-ink-200 dark:border-ink-800 px-5 py-2.5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold text-ink-900 dark:text-white tracking-tight">
              {t(activeTitle)}
            </h2>
            <div className="flex items-center gap-3">
              <TaskSelector />
              <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-ink-500 dark:text-ink-400">
                <span className="dot-ok" />
                {t('system.online')}
              </span>
            </div>
          </div>
        </header>

        <main className="p-5 lg:p-7">{children}</main>
      </div>

      {/* Mobile scrim */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink-950/50 lg:hidden animate-fade-in"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}
    </div>
  );
}
