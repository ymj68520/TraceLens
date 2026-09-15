import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

interface UseKeyboardShortcutsOptions {
  /** Opens the ShortcutsDialog; bound to the '?' key. */
  onOpenHelp: () => void;
}

/** Second half of a 'g' prefix sequence → target route. */
const G_SEQUENCES: Record<string, string> = {
  d: '/dashboard',
  t: '/tasks',
  f: '/files',
  s: '/search',
  c: '/cases',
  k: '/knowledge-graph',
  m: '/memory',
  a: '/android',
  o: '/oss',
  i: '/investigation',
  // r = reports/statistics page (统计报表).
  r: '/statistics',
};

/** How long the 'g' prefix stays armed while waiting for the next key. */
const SEQUENCE_RESET_MS = 1200;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/**
 * Global keydown shortcuts:
 * - '?'      → opens the shortcuts help dialog (via onOpenHelp)
 * - g then d/t/f/s/c/k/m/a/o/i/r → navigate to dashboard/tasks/files/search/
 *   cases/knowledge-graph/memory/android/oss/investigation/statistics
 *
 * Deliberately NOT handled here: ⌘K (Layout's command palette already owns
 * it) and Esc (owned by the open dialogs themselves). Keys typed while an
 * input, textarea, select or contentEditable element has focus are ignored,
 * as are any combos with modifier keys and IME composition.
 */
export function useKeyboardShortcuts({ onOpenHelp }: UseKeyboardShortcutsOptions): void {
  const navigate = useNavigate();

  // Latest-ref pattern so callers can pass an inline callback safely.
  const helpRef = useRef(onOpenHelp);
  helpRef.current = onOpenHelp;

  useEffect(() => {
    let pendingG = false;
    let timer: number | undefined;

    const resetPending = () => {
      pendingG = false;
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.isComposing) return;
      if (isEditableTarget(e.target)) return;

      if (e.key === '?') {
        e.preventDefault();
        helpRef.current();
        return;
      }

      const key = e.key.toLowerCase();

      if (key === 'g' && !e.repeat) {
        // Arm (or re-arm) the sequence prefix.
        resetPending();
        pendingG = true;
        timer = window.setTimeout(resetPending, SEQUENCE_RESET_MS);
        return;
      }

      if (pendingG) {
        resetPending();
        const href = G_SEQUENCES[key];
        if (href) {
          e.preventDefault();
          navigate(href);
        }
        // Any other key simply disarms the prefix.
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      resetPending();
    };
  }, [navigate]);
}

export default useKeyboardShortcuts;
