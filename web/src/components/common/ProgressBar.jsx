const ProgressBar = ({ value = 0, max = 100, size = 'md', color = 'blue', showLabel = false, label, className = '' }) => {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100);

  const sizes = {
    sm: 'h-1.5',
    md: 'h-2.5',
    lg: 'h-3.5',
  };

  const colors = {
    blue: 'from-primary-500 to-primary-400',
    green: 'from-emerald-500 to-emerald-400',
    red: 'from-rose-500 to-rose-400',
    yellow: 'from-amber-500 to-amber-400',
    purple: 'from-purple-500 to-purple-400',
  };

  return (
    <div className={`w-full ${className}`}>
      {(showLabel || label) && (
        <div className="flex justify-between mb-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
            {label || 'Progress'}
          </span>
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            {percentage.toFixed(1)}%
          </span>
        </div>
      )}
      <div className={`w-full bg-slate-200/60 dark:bg-slate-700/40 rounded-full ${sizes[size]} overflow-hidden`}>
        <div
          className={`${sizes[size]} rounded-full bg-gradient-to-r ${colors[color]} transition-all duration-500 ease-out relative`}
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={value}
          aria-valuemin={0}
          aria-valuemax={max}
        >
          {percentage > 5 && <div className="absolute inset-0 shimmer-bar rounded-full" />}
        </div>
      </div>
    </div>
  );
};

export default ProgressBar;
