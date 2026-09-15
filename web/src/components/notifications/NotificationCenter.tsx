import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {
  AlertCircle,
  Bell,
  BellOff,
  CheckCheck,
  CheckCircle2,
  Info,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
import { useAppNotifications } from '../../hooks/useAppNotifications';
import type { AppEventKind } from '../../lib/appEvents';
import { cn, formatRelativeTime } from '../../lib/utils';

const kindMeta: Record<AppEventKind, { icon: LucideIcon; iconClass: string }> = {
  success: { icon: CheckCircle2, iconClass: 'text-emerald-500 dark:text-emerald-400' },
  error: { icon: AlertCircle, iconClass: 'text-rose-500 dark:text-rose-400' },
  info: { icon: Info, iconClass: 'text-sky-500 dark:text-sky-400' },
};

const MAX_UNREAD_BADGE = 9;

const actionBtnClass =
  'inline-flex items-center gap-1 rounded px-1.5 py-1 text-2xs font-medium text-ink-500 ' +
  'transition-colors hover:bg-ink-100 hover:text-ink-800 disabled:pointer-events-none disabled:opacity-40 ' +
  'dark:text-ink-400 dark:hover:bg-ink-800 dark:hover:text-ink-200';

/**
 * Self-contained notification bell + dropdown panel, fed by the appEvents bus
 * via useAppNotifications. Wiring only needs to drop <NotificationCenter />
 * into the Layout header — no props.
 */
export function NotificationCenter() {
  const { events, unreadCount, readAt, markAllRead, markRead, clearAll } = useAppNotifications();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`通知中心${unreadCount > 0 ? `（${unreadCount} 条未读）` : ''}`}
          className="relative inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-700 dark:text-ink-400 dark:hover:bg-ink-800 dark:hover:text-ink-200"
        >
          <Bell size={17} />
          {unreadCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-accent-500 px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-white dark:ring-ink-925">
              {unreadCount > MAX_UNREAD_BADGE ? '9+' : unreadCount}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-[80] w-[340px] select-none rounded-xl card shadow-pop outline-none animate-fade-in"
        >
          <div className="flex items-center justify-between border-b border-ink-200/70 px-3.5 py-2.5 dark:border-ink-800">
            <span className="text-sm font-semibold text-ink-900 dark:text-ink-100">通知中心</span>
            <div className="flex items-center gap-1">
              <button type="button" className={actionBtnClass} onClick={markAllRead} disabled={unreadCount === 0}>
                <CheckCheck size={12} />
                全部已读
              </button>
              <button type="button" className={actionBtnClass} onClick={clearAll} disabled={events.length === 0}>
                <Trash2 size={12} />
                清空
              </button>
            </div>
          </div>

          {events.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
              <BellOff size={20} className="text-ink-300 dark:text-ink-600" />
              <p className="text-xs text-ink-400 dark:text-ink-500">暂无通知</p>
            </div>
          ) : (
            <div className="max-h-[360px] overflow-y-auto py-1">
              {events.map((evt) => {
                const meta = kindMeta[evt.kind];
                const Icon = meta.icon;
                const unread = evt.ts > readAt;
                return (
                  <DropdownMenu.Item
                    key={evt.id}
                    onSelect={(event) => {
                      // Keep the panel open; only record the read state.
                      event.preventDefault();
                      if (unread) markRead(evt.id);
                    }}
                    className={cn(
                      'flex cursor-pointer items-start gap-2.5 px-3.5 py-2.5 outline-none transition-colors',
                      'data-[highlighted]:bg-ink-50 dark:data-[highlighted]:bg-ink-900/60',
                      unread && 'bg-accent-50/60 dark:bg-accent-500/5',
                    )}
                  >
                    <Icon size={15} className={cn('mt-0.5 shrink-0', meta.iconClass)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <p
                          className={cn(
                            'truncate text-xs',
                            unread ? 'font-semibold text-ink-900 dark:text-ink-100' : 'text-ink-700 dark:text-ink-300',
                          )}
                        >
                          {evt.title}
                        </p>
                        <span className="shrink-0 text-2xs text-ink-400 dark:text-ink-500">
                          {formatRelativeTime(evt.ts)}
                        </span>
                      </div>
                      {evt.detail && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-ink-500 dark:text-ink-400">{evt.detail}</p>
                      )}
                    </div>
                    {unread && (
                      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
                    )}
                  </DropdownMenu.Item>
                );
              })}
            </div>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default NotificationCenter;
