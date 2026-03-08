import { motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

const Button = ({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  disabled = false,
  loading = false,
  fullWidth = false,
  type = 'button',
  onClick,
  icon: Icon,
  iconPosition = 'left',
  ...props
}) => {
  const base =
    'relative inline-flex items-center justify-center font-semibold rounded-xl focus:outline-none focus:ring-2 focus:ring-offset-2 dark:focus:ring-offset-slate-900 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:scale-100';

  const variants = {
    primary:
      'bg-gradient-to-r from-primary-600 to-primary-500 text-white hover:from-primary-500 hover:to-primary-400 focus:ring-primary-500 shadow-md hover:shadow-glow-primary active:scale-[0.97]',
    secondary:
      'bg-slate-200/80 text-slate-800 hover:bg-slate-300/80 focus:ring-slate-400 dark:bg-slate-700/60 dark:text-slate-200 dark:hover:bg-slate-600/60 active:scale-[0.97]',
    success:
      'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white hover:from-emerald-500 hover:from-emerald-400 focus:ring-emerald-500 shadow-md hover:shadow-glow-success active:scale-[0.97]',
    danger:
      'bg-gradient-to-r from-rose-600 to-rose-500 text-white hover:from-rose-500 hover:to-rose-400 focus:ring-rose-500 shadow-md hover:shadow-glow-danger active:scale-[0.97]',
    outline:
      'border-2 border-primary-500/50 text-primary-600 dark:text-primary-400 hover:bg-primary-50/50 dark:hover:bg-primary-950/30 focus:ring-primary-500 active:scale-[0.97]',
    ghost:
      'text-slate-600 dark:text-slate-400 hover:bg-slate-100/60 dark:hover:bg-slate-800/60 focus:ring-slate-400 active:scale-[0.97]',
  };

  const sizes = {
    sm: 'px-3.5 py-1.5 text-sm gap-1.5',
    md: 'px-5 py-2.5 text-sm gap-2',
    lg: 'px-7 py-3 text-base gap-2.5',
  };

  const classes = clsx(
    base,
    variants[variant] || variants.primary,
    sizes[size] || sizes.md,
    fullWidth && 'w-full',
    loading && 'text-transparent cursor-wait',
    className
  );

  return (
    <motion.button
      type={type}
      className={classes}
      disabled={disabled || loading}
      onClick={onClick}
      whileHover={!(disabled || loading) ? { scale: 1.02 } : {}}
      whileTap={!(disabled || loading) ? { scale: 0.97 } : {}}
      {...props}
    >
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-current">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      )}
      
      {Icon && iconPosition === 'left' && <Icon className={clsx('flex-shrink-0', size === 'sm' ? 'w-4 h-4' : 'w-5 h-5')} />}
      {children}
      {Icon && iconPosition === 'right' && <Icon className={clsx('flex-shrink-0', size === 'sm' ? 'w-4 h-4' : 'w-5 h-5')} />}
    </motion.button>
  );
};

export default Button;
