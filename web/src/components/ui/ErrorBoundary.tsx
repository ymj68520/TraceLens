import { Component, type ReactNode } from 'react';
import { AlertOctagon } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error('ErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-ink-50 dark:bg-ink-950 p-6">
          <div className="card card-pad max-w-md w-full text-center">
            <div className="inline-flex p-3 rounded-full bg-rose-50 dark:bg-rose-500/10 text-rose-500 mb-4">
              <AlertOctagon size={28} />
            </div>
            <h1 className="text-lg font-semibold text-ink-900 dark:text-ink-100 mb-2">
              页面出现异常
            </h1>
            <p className="text-sm text-ink-500 dark:text-ink-400 mb-4 break-all">
              {this.state.error?.message || '未知错误'}
            </p>
            <button
              type="button"
              className="btn-primary"
              onClick={() => window.location.reload()}
            >
              重新加载
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
