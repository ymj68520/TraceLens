import { useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { toggleSidebar } from '../../store/uiSlice';
import TaskSelector from '../common/TaskSelector';
import { useTranslation } from '../../hooks/useTranslation';
import { motion } from 'framer-motion';
import {
  LayoutDashboard, ListTodo, Clock, FolderOpen, Brain, Network,
  Smartphone, Cloud, Search, BarChart3, Settings, Menu, X, ChevronLeft, ChevronRight, FileText,
} from 'lucide-react';

const Layout = ({ children }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const dispatch = useDispatch();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const currentTaskId = searchParams.get('task_id');
  const { sidebarOpen } = useSelector((state) => state.ui);
  const { t } = useTranslation();

  const navigation = [
    { name: t('nav.dashboard'), href: '/dashboard', icon: LayoutDashboard },
    { name: t('nav.tasks'), href: '/tasks', icon: ListTodo },
    { name: t('nav.timeline'), href: '/timeline', icon: Clock },
    { name: t('nav.files'), href: '/files', icon: FolderOpen },
    { name: t('nav.ai_descriptions'), href: '/llm-descriptions', icon: Brain },
    { name: '案情报告', href: '/case-report', icon: FileText },
    { name: t('nav.knowledge_graph'), href: '/knowledge-graph', icon: Network },
    { name: t('nav.android'), href: '/android', icon: Smartphone },
    { name: 'OSS 分析', href: '/oss', icon: Cloud },
    { name: t('nav.search'), href: '/search', icon: Search },
    { name: t('nav.statistics'), href: '/statistics', icon: BarChart3 },
    { name: t('nav.settings'), href: '/settings', icon: Settings },
  ];

  const isActive = (path) => location.pathname === path;

  const getLinkUrl = (href) => {
    const taskContextPages = ['/timeline', '/files', '/llm-descriptions', '/case-report', '/knowledge-graph', '/android', '/oss', '/search', '/statistics'];
    if (currentTaskId && taskContextPages.includes(href)) {
      return `${href}?task_id=${currentTaskId}`;
    }
    return href;
  };

  return (
    <div className="min-h-screen bg-mesh-light dark:bg-mesh-dark transition-colors duration-300">
      {/* Mobile menu button */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 glass-strong px-4 py-3 flex items-center">
        <button
          type="button"
          className="p-2 rounded-xl text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-colors"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span className="sr-only">Open sidebar</span>
          {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
        <h1 className="ml-3 text-lg font-bold text-slate-900 dark:text-white tracking-tight">
          {t('app.title')}
        </h1>
      </div>

      {/* Sidebar */}
      <div
        className={`fixed inset-y-0 left-0 z-40 w-64 transition-transform duration-300 ease-in-out lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
          } ${mobileMenuOpen ? 'translate-x-0' : ''}`}
      >
        <div className="flex flex-col h-full bg-gradient-to-b from-slate-900 via-slate-900 to-primary-950 border-r border-slate-700/30">
          {/* Logo */}
          <div className="hidden lg:flex items-center h-16 px-6 border-b border-slate-700/30">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-purple-500 flex items-center justify-center">
                <Search size={16} className="text-white" />
              </div>
              <h1 className="text-lg font-bold text-white tracking-tight">{t('app.title')}</h1>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto px-3 py-4 pt-20 lg:pt-4">
            <ul className="space-y-1">
              {navigation.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      to={getLinkUrl(item.href)}
                      className={`group flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-xl transition-all duration-200 ${active
                        ? 'bg-primary-500/20 text-primary-300 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.3)]'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
                        }`}
                      onClick={() => setMobileMenuOpen(false)}
                    >
                      <Icon
                        size={18}
                        className={`flex-shrink-0 transition-colors ${active ? 'text-primary-400' : 'text-slate-500 group-hover:text-slate-300'
                          }`}
                      />
                      <span>{item.name}</span>
                      {active && (
                        <motion.div
                          layoutId="active-indicator"
                          className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-400 shadow-[0_0_6px_rgba(99,102,241,0.8)]"
                        />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Sidebar footer */}
          <div className="border-t border-slate-700/30 p-4">
            <button
              onClick={() => dispatch(toggleSidebar())}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-slate-400 hover:text-slate-200 bg-white/5 rounded-xl hover:bg-white/10 transition-all"
            >
              {sidebarOpen ? <><ChevronLeft size={16} />{t('sidebar.collapse')}</> : <><ChevronRight size={16} />{t('sidebar.expand')}</>}
            </button>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div
        className={`lg:pl-64 pt-16 lg:pt-0 transition-all duration-300 ${sidebarOpen ? 'lg:pl-64' : 'lg:pl-0'
          }`}
      >
        {/* Header */}
        <header className="sticky top-0 z-30 glass-strong border-b border-white/10 dark:border-slate-700/30 px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <button
                onClick={() => dispatch(toggleSidebar())}
                className="lg:hidden p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-colors"
              >
                <Menu size={20} />
              </button>
              <h2 className="ml-2 text-xl font-bold text-slate-900 dark:text-white tracking-tight">
                {navigation.find((item) => isActive(item.href))?.name || t('nav.dashboard')}
              </h2>
            </div>
            <div className="flex items-center gap-4">
              <TaskSelector />
              <div className="hidden sm:flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <div className="status-dot status-dot-online" />
                <span>{t('system.online')}</span>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-6 lg:p-8">{children}</main>
      </div>

      {/* Mobile sidebar overlay */}
      {mobileMenuOpen && (
        <motion.div
          className="fixed inset-0 z-30 bg-slate-900/60 backdrop-blur-sm lg:hidden"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          onClick={() => setMobileMenuOpen(false)}
        />
      )}
    </div>
  );
};

export default Layout;
