import { useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { toggleSidebar } from '../../store/uiSlice';
import TaskSelector from '../common/TaskSelector';
import { useTranslation } from '../../hooks/useTranslation';

const Layout = ({ children }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const dispatch = useDispatch();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const currentTaskId = searchParams.get('task_id');
  const { sidebarOpen } = useSelector((state) => state.ui);
  const { t } = useTranslation();

  const navigation = [
    { name: t('nav.dashboard'), href: '/dashboard', icon: '📊' },
    { name: t('nav.tasks'), href: '/tasks', icon: '📋' },
    { name: t('nav.timeline'), href: '/timeline', icon: '📈' },
    { name: t('nav.files'), href: '/files', icon: '📁' },
    { name: t('nav.ai_descriptions'), href: '/llm-descriptions', icon: '🧠' },
    { name: t('nav.knowledge_graph'), href: '/knowledge-graph', icon: '🕸️' },
    { name: t('nav.android'), href: '/android', icon: '🤖' },
    { name: 'OSS 分析', href: '/oss', icon: '☁️' },
    { name: t('nav.search'), href: '/search', icon: '🔍' },
    { name: t('nav.statistics'), href: '/statistics', icon: '📊' },
    { name: t('nav.settings'), href: '/settings', icon: '⚙️' },
  ];

  const isActive = (path) => location.pathname === path;

  // Helper to construct link URL with preserved task_id
  const getLinkUrl = (href) => {
    // List of pages that should preserve the task context
    const taskContextPages = ['/timeline', '/files', '/llm-descriptions', '/knowledge-graph', '/android', '/oss', '/search', '/statistics'];

    if (currentTaskId && taskContextPages.includes(href)) {
      return `${href}?task_id=${currentTaskId}`;
    }
    return href;
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors duration-200">
      {/* Mobile menu button */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <button
          type="button"
          className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span className="sr-only">Open sidebar</span>
          <svg
            className="h-6 w-6"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth="1.5"
            stroke="currentColor"
          >
            {mobileMenuOpen ? (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            ) : (
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
              />
            )}
          </svg>
        </button>
        <h1 className="ml-3 text-lg font-semibold text-gray-900 dark:text-white">
          {t('app.title')}
        </h1>
      </div>

      {/* Sidebar - Desktop */}
      <div
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 pt-16 transition-transform duration-300 ease-in-out lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
          } ${mobileMenuOpen ? 'translate-x-0' : ''}`}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="hidden lg:flex items-center justify-center h-16 border-b border-gray-200 dark:border-gray-700 px-6">
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">
              {t('app.title')}
            </h1>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto px-3 py-4">
            <ul className="space-y-1">
              {navigation.map((item) => (
                <li key={item.name}>
                  <Link
                    to={getLinkUrl(item.href)}
                    className={`flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors ${isActive(item.href)
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-900 dark:text-blue-100'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      }`}
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <span className="mr-3 text-lg">{item.icon}</span>
                    {item.name}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          {/* Sidebar footer */}
          <div className="border-t border-gray-200 dark:border-gray-700 p-4">
            <button
              onClick={() => dispatch(toggleSidebar())}
              className="w-full flex items-center justify-center px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            >
              {sidebarOpen ? `« ${t('sidebar.collapse')}` : `» ${t('sidebar.expand')}`}
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
        <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 transition-colors duration-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <button
                onClick={() => dispatch(toggleSidebar())}
                className="lg:hidden p-2 rounded-md text-gray-400 hover:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <svg
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth="1.5"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
                  />
                </svg>
              </button>
              <h2 className="ml-4 text-2xl font-semibold text-gray-900 dark:text-white">
                {navigation.find((item) => isActive(item.href))?.name ||
                  t('nav.dashboard')}
              </h2>
            </div>
            <div className="flex items-center space-x-4">
              <TaskSelector />
              <div className="text-sm text-gray-500 dark:text-gray-400">
                {t('system.status')}: <span className="text-green-600 font-medium">● {t('system.online')}</span>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-6 transition-colors duration-200">{children}</main>
      </div>

      {/* Mobile sidebar overlay */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-gray-600 bg-opacity-75 lg:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}
    </div>
  );
};

export default Layout;
