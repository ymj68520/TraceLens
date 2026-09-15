import { Component, type ErrorInfo, type ReactNode } from 'react';
import { RotateCcw } from 'lucide-react';
import BrandLogo from '../ui/BrandLogo';

interface PageErrorBoundaryProps {
  children: ReactNode;
}

interface PageErrorBoundaryState {
  error: Error | null;
}

/**
 * Page-level error boundary. Wrap a routed page's content so one broken page
 * shows a branded, recoverable fallback instead of blanking the whole shell.
 * "重试" resets the boundary; navigating to another page (new children) also
 * clears the error automatically.
 */
export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('PageErrorBoundary caught:', error, info.componentStack);
  }

  componentDidUpdate(prevProps: PageErrorBoundaryProps) {
    // The router renders different children per route — treat that as recovery.
    if (this.state.error !== null && prevProps.children !== this.props.children) {
      this.setState({ error: null });
    }
  }

  private reset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (error === null) return this.props.children;

    const showStack = import.meta.env.DEV && Boolean(error.stack);

    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <div className="card card-pad w-full max-w-md">
          <div className="mb-4 flex items-center gap-3">
            <BrandLogo size={32} />
            <div>
              <h1 className="text-sm font-semibold text-ink-900 dark:text-ink-100">页面出错了</h1>
              <p className="text-xs text-ink-500 dark:text-ink-400">该页面渲染时发生异常，其他页面不受影响。</p>
            </div>
          </div>

          <div className="rounded-md border border-ink-200 bg-ink-50 px-3 py-2.5 dark:border-ink-800 dark:bg-ink-900">
            <p className="break-all text-xs font-medium text-rose-600 dark:text-rose-400">
              {error.message || '未知错误'}
            </p>
            {showStack && (
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-2xs leading-relaxed text-ink-500 dark:text-ink-400">
                {error.stack}
              </pre>
            )}
          </div>

          <button type="button" className="btn-secondary btn-sm mt-4" onClick={this.reset}>
            <RotateCcw size={14} />
            重试
          </button>
        </div>
      </div>
    );
  }
}

export default PageErrorBoundary;
