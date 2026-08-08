/**
 * GenericArtifactTable
 *
 * Renders any platform artifact section (contacts, win_users, linux_shell, …)
 * from a RecordPage. Columns come from artifactColumns[sectionId]; if a column
 * definition is missing, columns are derived from the record keys so a new
 * backend section renders immediately without a frontend change.
 *
 * Empty values render the "—" placeholder to match the reference report's
 * "full schema always visible" requirement.
 */
import { useMemo } from 'react';
import { SectionCard, EmptySection, val } from './shared';
import { resolveColumns } from './artifactColumns';

export default function GenericArtifactTable({ sectionId, title, pageData }) {
  const records = pageData?.records || [];
  const total = pageData?.total ?? records.length;
  const start = ((pageData?.page || 1) - 1) * (pageData?.page_size || 0);

  const columns = useMemo(
    () => resolveColumns(sectionId, records),
    [sectionId, records],
  );

  return (
    <SectionCard title={title} total={total}>
      {records.length === 0 ? (
        <EmptySection />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table className="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-700">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2 font-semibold w-10">#</th>
                {columns.map((c) => (
                  <th key={c.key} className="px-3 py-2 font-semibold whitespace-nowrap">{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-700 dark:bg-slate-900/70">
              {records.map((r, i) => (
                <tr key={i} className="align-top">
                  <td className="px-3 py-2 text-slate-400">{start + i + 1}</td>
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-2 max-w-md break-all text-slate-600 dark:text-slate-300">
                      {c.format ? c.format(r[c.key]) : val(r[c.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
