import AttachmentList from './AttachmentList';
import RecordBadges from './RecordBadges';

function displayValue(value) {
  if (value === null || value === undefined) return '';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function sourceMetadata(record) {
  return [
    ['路径', record?.source_path],
    ['表', record?.source_table],
    ['记录 ID', record?.source_record_id],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
}

function RecordDetails({ record }) {
  const metadata = sourceMetadata(record);
  const hashes = Object.entries(record?.hashes || {});

  return (
    <div className="mt-3 space-y-2 text-xs text-slate-500 dark:text-slate-400">
      {metadata.length > 0 && (
        <dl className="flex flex-wrap gap-x-4 gap-y-1">
          {metadata.map(([label, value]) => (
            <div key={label} className="flex gap-1">
              <dt>{label}:</dt>
              <dd className="break-all font-mono">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {hashes.length > 0 && (
        <dl className="space-y-1">
          {hashes.map(([algorithm, digest]) => (
            <div key={algorithm} className="flex gap-1">
              <dt>{algorithm}:</dt>
              <dd className="break-all font-mono">{String(digest)}</dd>
            </div>
          ))}
        </dl>
      )}
      <AttachmentList attachments={record?.attachments} />
    </div>
  );
}

export default function GenericTableRenderer({ records = [] }) {
  const fieldColumns = [...new Set(records.flatMap((record) => Object.keys(record?.fields || {})))];

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-700">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          <tr>
            <th scope="col" className="px-4 py-3 font-semibold">记录</th>
            {fieldColumns.map((field) => <th key={field} scope="col" className="px-4 py-3 font-semibold">{field}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-700 dark:bg-slate-900/70">
          {records.map((record, index) => {
            const title = record?.title || record?.record_id || `记录 ${index + 1}`;
            return (
              <tr key={record?.record_id || `${title}-${index}`} data-record-id={record?.record_id} className="scroll-mt-24 align-top">
                <td className="min-w-64 px-4 py-3">
                  <p className="font-semibold text-slate-900 dark:text-slate-100">{title}</p>
                  <div className="mt-2"><RecordBadges record={record} /></div>
                  <RecordDetails record={record} />
                </td>
                {fieldColumns.map((field) => (
                  <td key={field} className="min-w-44 max-w-sm break-words px-4 py-3 text-slate-700 dark:text-slate-200">
                    {displayValue(record?.fields?.[field])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

GenericTableRenderer.displayName = 'GenericTableRenderer';
