import type { MarkdownBlock } from './reportModel';
import { cx } from '../../lib/utils';

const NUMERIC_COL_RE = /count|total|size|bytes|num|^id$/i;

const isNumericColumn = (col: string): boolean => NUMERIC_COL_RE.test(col);

function BlockTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto border border-ink-200 dark:border-ink-800 rounded-md">
      <table className="table-shell">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (
                <td
                  key={j}
                  className={cx('text-xs max-w-[240px] truncate', isNumericColumn(columns[j] ?? '') && 'font-mono tabular-nums')}
                >
                  {cell || '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Block-level markdown renderer for parsed narrative sections. */
export default function MarkdownLite({ blocks }: { blocks: MarkdownBlock[] }) {
  if (blocks.length === 0) {
    return <p className="text-xs text-ink-400 dark:text-ink-500">本章节暂无内容。</p>;
  }
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        switch (block.type) {
          case 'paragraph':
            return (
              <p key={i} className="text-sm leading-relaxed text-ink-700 dark:text-ink-200 whitespace-pre-wrap">
                {block.text}
              </p>
            );
          case 'list':
            return (
              <ul key={i} className="list-disc pl-5 space-y-1 text-sm text-ink-700 dark:text-ink-200">
                {block.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ul>
            );
          case 'code':
            return (
              <pre key={i} className="code-block whitespace-pre-wrap text-2xs">
                {block.text}
              </pre>
            );
          case 'table':
            return <BlockTable key={i} columns={block.columns} rows={block.rows} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
