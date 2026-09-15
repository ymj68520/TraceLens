import type { ComponentProps, ReactNode } from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { cn } from '../../lib/utils';

/** Styled Radix dropdown primitives — ink surface, flat items, danger variant. */

export const Dropdown = DropdownMenu.Root;

export function DropdownTrigger({ children, ...rest }: ComponentProps<typeof DropdownMenu.Trigger>) {
  return <DropdownMenu.Trigger asChild {...rest}>{children}</DropdownMenu.Trigger>;
}

export function DropdownContent({
  children,
  align = 'end',
  className,
}: {
  children: ReactNode;
  align?: 'start' | 'center' | 'end';
  className?: string;
}) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        align={align}
        sideOffset={4}
        className={cn(
          'z-[80] min-w-[10rem] card shadow-pop p-1 animate-fade-in',
          className,
        )}
      >
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
}

export function DropdownItem({
  children,
  danger = false,
  className,
  ...rest
}: ComponentProps<typeof DropdownMenu.Item> & { danger?: boolean }) {
  return (
    <DropdownMenu.Item
      className={cn(
        'flex cursor-pointer select-none items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium outline-none',
        danger
          ? 'text-rose-600 dark:text-rose-400 data-[highlighted]:bg-rose-50 dark:data-[highlighted]:bg-rose-500/10'
          : 'text-ink-700 dark:text-ink-300 data-[highlighted]:bg-ink-100 dark:data-[highlighted]:bg-ink-800',
        'data-[disabled=true]:opacity-50 data-[disabled=true]:pointer-events-none',
        className,
      )}
      {...rest}
    >
      {children}
    </DropdownMenu.Item>
  );
}

export function DropdownSeparator() {
  return <DropdownMenu.Separator className="my-1 h-px bg-ink-200 dark:bg-ink-800" />;
}

export function DropdownLabel({ children }: { children: ReactNode }) {
  return <DropdownMenu.Label className="section-label px-2.5 py-1.5">{children}</DropdownMenu.Label>;
}

export default Dropdown;
