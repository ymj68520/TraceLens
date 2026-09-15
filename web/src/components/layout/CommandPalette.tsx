import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Command } from 'cmdk';
import { useAppSelector } from '../../store';
import { buildNavSections, TASK_CONTEXT_PAGES, NAV_GROUP_LABELS } from './navConfig';
import { basename } from '../../lib/utils';
import { useTranslation } from '../../hooks/useTranslation';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Global ⌘K / Ctrl+K palette: filters pages and recent tasks.
 * Task entries deep-link into the timeline with the task context attached.
 */
export default function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t } = useTranslation();
  const showTerminal = useAppSelector((state) => state.settings.showTerminal);
  const tasks = useAppSelector((state) => state.tasks.tasks);
  const currentTaskId = searchParams.get('task_id');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);

  const go = (href: string) => {
    onOpenChange(false);
    // href may be a bare path ("­/dashboard") or already carry a query
    // ("­/timeline?task_id=…") — never hand relative paths to `new URL()`.
    const [path, query = ''] = href.split('?');
    const params = new URLSearchParams(query);
    if (currentTaskId && TASK_CONTEXT_PAGES.has(path) && !params.has('task_id')) {
      params.set('task_id', currentTaskId);
      navigate(`${path}?${params.toString()}`);
      return;
    }
    navigate(href);
  };

  const navSections = buildNavSections(showTerminal);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="全局搜索"
      overlayClassName="cmdk-overlay"
      contentClassName="cmdk-container"
    >
      <Command.Input className="cmdk-input" placeholder="搜索页面、任务…" autoFocus />
      <Command.List className="max-h-[320px] overflow-y-auto overscroll-contain py-1.5">
        <Command.Empty className="cmdk-empty">没有匹配的结果</Command.Empty>

        {navSections.map((section) => (
          <Command.Group key={section.label} heading={NAV_GROUP_LABELS[section.label]} className="cmdk-group">
            {section.items.map((item) => (
              <Command.Item
                key={item.href}
                value={`${t(item.key)} ${item.href}`}
                onSelect={() => go(item.href)}
                className="cmdk-item"
              >
                <item.icon size={15} className="text-ink-400 dark:text-ink-500" />
                {t(item.key)}
              </Command.Item>
            ))}
          </Command.Group>
        ))}

        {tasks.length > 0 && (
          <Command.Group heading="最近任务" className="cmdk-group">
            {tasks.slice(0, 6).map((task) => (
              <Command.Item
                key={task.id}
                value={`任务 ${basename(task.image_path)} ${task.id}`}
                onSelect={() => go(`/timeline?task_id=${task.id}`)}
                className="cmdk-item"
                data-task-id={task.id}
              >
                <span className="font-mono text-2xs text-ink-400">{task.id.substring(0, 8)}</span>
                <span className="truncate">{basename(task.image_path)}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}
