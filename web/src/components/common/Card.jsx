import { motion } from 'framer-motion';

const Card = ({ children, title, subtitle, className = '', animate = true, ...props }) => {
  const Wrapper = animate ? motion.div : 'div';
  const motionProps = animate
    ? {
      initial: { opacity: 0, y: 12 },
      animate: { opacity: 1, y: 0 },
      transition: { duration: 0.4, ease: 'easeOut' },
    }
    : {};

  return (
    <Wrapper
      className={`glass rounded-2xl overflow-hidden transition-all duration-300 hover:shadow-glass-lg ${className}`}
      {...motionProps}
      {...props}
    >
      {(title || subtitle) && (
        <div className="px-6 py-4 border-b border-white/10 dark:border-slate-700/40">
          {title && (
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
              {title}
            </h3>
          )}
          {subtitle && (
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
          )}
        </div>
      )}
      <div className="px-6 py-4 text-slate-700 dark:text-slate-300">{children}</div>
    </Wrapper>
  );
};

export default Card;
