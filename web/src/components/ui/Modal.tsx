import type { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cx } from '../../lib/utils';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  width?: 'sm' | 'md' | 'lg' | 'xl';
}

const widths = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

/**
 * Radix Dialog wrapper. Focus trap, scroll lock, Esc and overlay click are
 * handled by Radix; callers keep the simple { open, onClose } contract.
 */
export function Modal({ open, onClose, title, children, width = 'md' }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-[60] bg-ink-950/40" />
        <Dialog.Content
          className={cx(
            'dialog-content fixed left-1/2 top-1/2 z-[70] w-full -translate-x-1/2 -translate-y-1/2',
            'card shadow-pop max-h-[85vh] flex flex-col focus:outline-none',
            widths[width],
          )}
        >
          {title !== undefined ? (
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-ink-200 dark:border-ink-800">
              <Dialog.Title className="text-sm font-semibold text-ink-900 dark:text-ink-100">
                {title}
              </Dialog.Title>
              <Dialog.Close
                className="p-1.5 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                aria-label="关闭"
              >
                <X size={16} />
              </Dialog.Close>
            </div>
          ) : (
            <>
              {/* Accessibility: Radix requires a title even when visually hidden. */}
              <Dialog.Title className="sr-only">对话框</Dialog.Title>
              <Dialog.Close
                className="absolute right-3.5 top-3.5 p-1.5 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                aria-label="关闭"
              >
                <X size={16} />
              </Dialog.Close>
            </>
          )}
          <div className="px-5 py-4 overflow-y-auto">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default Modal;
