import type { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

interface ShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface ShortcutDef {
  label: string;
  keys: string[];
  /** keys 是先后按下的序列（先 g 再 d），渲染为「然后」分隔。 */
  sequence?: boolean;
}

interface ShortcutGroup {
  title: string;
  shortcuts: ShortcutDef[];
}

const GROUPS: ShortcutGroup[] = [
  {
    title: '全局',
    shortcuts: [
      { label: '打开搜索', keys: ['⌘', 'K'] },
      { label: '快捷键帮助', keys: ['?'] },
      { label: '仪表盘', keys: ['g', 'd'], sequence: true },
      { label: '任务列表', keys: ['g', 't'], sequence: true },
      { label: '文件管理', keys: ['g', 'f'], sequence: true },
      { label: '搜索', keys: ['g', 's'], sequence: true },
      { label: '案件列表', keys: ['g', 'c'], sequence: true },
      { label: '知识图谱', keys: ['g', 'k'], sequence: true },
      { label: '内存取证', keys: ['g', 'm'], sequence: true },
      { label: '安卓取证', keys: ['g', 'a'], sequence: true },
      { label: 'OSS 分析', keys: ['g', 'o'], sequence: true },
      { label: '调查工作台', keys: ['g', 'i'], sequence: true },
      { label: '统计报表', keys: ['g', 'r'], sequence: true },
      { label: '关闭弹窗', keys: ['Esc'] },
    ],
  },
  {
    title: '表格通用',
    shortcuts: [
      { label: '选中行', keys: ['点击'] },
      { label: '列排序', keys: ['表头'] },
    ],
  },
];

function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

function ShortcutKeys({ keys, sequence }: ShortcutDef) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {keys.map((key, index) => (
        <span key={`${index}-${key}`} className="flex items-center gap-1">
          {index > 0 && sequence && (
            <span className="text-2xs text-ink-400 dark:text-ink-500">然后</span>
          )}
          <Kbd>{key}</Kbd>
        </span>
      ))}
    </span>
  );
}

/**
 * Keyboard shortcut cheat sheet (Radix Dialog). Overlay reuses the
 * .cmdk-overlay class; content mirrors the command palette card style.
 */
export function ShortcutsDialog({ open, onOpenChange }: ShortcutsDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="cmdk-overlay" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[80] flex max-h-[85vh] w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col card shadow-pop outline-none">
          <div className="flex items-center justify-between border-b border-ink-200 px-5 py-3.5 dark:border-ink-800">
            <Dialog.Title className="text-sm font-semibold text-ink-900 dark:text-ink-100">
              键盘快捷键
            </Dialog.Title>
            <Dialog.Close
              className="rounded-md p-1.5 text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-600 dark:hover:bg-ink-800 dark:hover:text-ink-200"
              aria-label="关闭"
            >
              <X size={16} />
            </Dialog.Close>
          </div>

          <div className="grid gap-x-8 gap-y-5 overflow-y-auto px-5 py-4 sm:grid-cols-2">
            {GROUPS.map((group) => (
              <section key={group.title}>
                <h3 className="section-label mb-2">{group.title}</h3>
                <ul className="space-y-0.5">
                  {group.shortcuts.map((shortcut) => (
                    <li
                      key={shortcut.label}
                      className="flex items-center justify-between gap-4 rounded-md px-2 py-1.5 hover:bg-ink-50 dark:hover:bg-ink-900/50"
                    >
                      <span className="text-xs text-ink-600 dark:text-ink-300">{shortcut.label}</span>
                      <ShortcutKeys {...shortcut} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <Dialog.Description className="border-t border-ink-200 px-5 py-2.5 text-2xs text-ink-400 dark:border-ink-800 dark:text-ink-500">
            在输入框中输入时，全局快捷键不会触发。
          </Dialog.Description>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default ShortcutsDialog;
