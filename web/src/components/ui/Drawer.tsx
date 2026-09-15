import type { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cx } from '../../lib/utils';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: 'md' | 'lg' | 'xl';
}

const widths = {
  md: 'max-w-md',
  lg: 'max-w-xl',
  xl: 'max-w-3xl',
};

/**
 * Right-hand slide-over panel (Radix Dialog). Use for detail views that
 * should not pull the user out of the list context — file preview, event
 * detail, case inspector.
 */
export function Drawer({ open, onClose, title, description, children, footer, width = 'lg' }: DrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-[60] bg-ink-950/40" />
        <Dialog.Content
          className={cx(
            'drawer-content fixed inset-y-0 right-0 z-[70] w-full flex flex-col',
            'bg-white dark:bg-ink-925 border-l border-ink-200 dark:border-ink-800 shadow-drawer focus:outline-none',
            widths[width],
          )}
        >
          <div className="flex items-start justify-between px-5 py-3.5 border-b border-ink-200 dark:border-ink-800 shrink-0">
            <div className="min-w-0">
              <Dialog.Title className="text-sm font-semibold text-ink-900 dark:text-ink-100 truncate">
                {title ?? '详情'}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="mt-0.5 text-xs text-ink-500 dark:text-ink-400 truncate">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close
              className="p-1.5 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors shrink-0"
              aria-label="关闭"
            >
              <X size={16} />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="px-5 py-3.5 border-t border-ink-200 dark:border-ink-800 shrink-0 bg-ink-50/60 dark:bg-ink-900/60">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Key-value row used inside drawers for structured record details. */
export function DetailRow({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-ink-100 dark:border-ink-800/60 last:border-0">
      <span className="w-24 shrink-0 text-2xs font-medium text-ink-400 dark:text-ink-500 pt-0.5">{label}</span>
      <span className={cx('min-w-0 flex-1 text-xs text-ink-800 dark:text-ink-200 break-all', mono && 'font-mono')}>
        {children}
      </span>
    </div>
  );
}

export default Drawer;
