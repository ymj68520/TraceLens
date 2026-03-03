const Badge = ({ children, variant = 'gray', size = 'md', className = '' }) => {
  const variants = {
    gray: 'bg-slate-100/80 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300 ring-1 ring-slate-200/50 dark:ring-slate-600/30',
    blue: 'bg-primary-100/80 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300 ring-1 ring-primary-200/50 dark:ring-primary-700/30',
    green: 'bg-emerald-100/80 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 ring-1 ring-emerald-200/50 dark:ring-emerald-700/30',
    red: 'bg-rose-100/80 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300 ring-1 ring-rose-200/50 dark:ring-rose-700/30',
    yellow: 'bg-amber-100/80 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 ring-1 ring-amber-200/50 dark:ring-amber-700/30',
    purple: 'bg-purple-100/80 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300 ring-1 ring-purple-200/50 dark:ring-purple-700/30',
  };

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-0.5 text-xs font-medium',
    lg: 'px-3 py-1 text-sm font-medium',
  };

  return (
    <span
      className={`inline-flex items-center rounded-lg backdrop-blur-sm ${variants[variant] || variants.gray} ${sizes[size] || sizes.md} ${className}`}
    >
      {children}
    </span>
  );
};

export default Badge;
