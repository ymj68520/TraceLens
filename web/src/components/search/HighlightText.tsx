import { useMemo } from 'react';
import { buildHighlightRegex } from './searchUtils';

/* Light-amber hit markers with dark variants; kept as a component so every
 * surface (rows, drawer, snippets) highlights identically. */
const MARK_CLASS = 'rounded-sm bg-amber-100 px-0.5 text-amber-900 dark:bg-amber-500/25 dark:text-amber-100';

/** Renders `text` with every case-insensitive match of the query in <mark>. */
export default function HighlightText({ text, query }: { text: string; query: string }) {
  const parts = useMemo(() => {
    const regex = buildHighlightRegex(query);
    if (!regex) return null;
    return text.split(regex);
  }, [text, query]);

  if (!parts) return <>{text}</>;
  return (
    <>
      {/* With a capture group, String.split puts matches at odd indices. */}
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className={MARK_CLASS}>
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}
