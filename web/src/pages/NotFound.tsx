import { Link } from 'react-router-dom';
import { FileQuestionMark } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <FileQuestionMark size={40} className="text-ink-300 dark:text-ink-600 mb-4" />
      <h1 className="text-lg font-semibold text-ink-900 dark:text-ink-100">页面不存在</h1>
      <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">您访问的地址没有对应的页面。</p>
      <Link to="/dashboard" className="btn-primary mt-5">
        返回仪表盘
      </Link>
    </div>
  );
}
