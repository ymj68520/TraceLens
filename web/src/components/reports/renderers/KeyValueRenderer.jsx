import AttachmentList from './AttachmentList';
import RecordBadges from './RecordBadges';

function displayValue(value) {
  if (value === null || value === undefined) return '';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export default function KeyValueRenderer({ records = [] }) {
  return (
    <div className="grid gap-4">
      {records.map((record, index) => {
        const title = record?.title || record?.record_id || `记录 ${index + 1}`;
        const properties = [
          ['timestamp', record?.timestamp],
          ...Object.entries(record?.fields || {}),
          ['source_path', record?.source_path],
          ['source_table', record?.source_table],
          ['source_record_id', record?.source_record_id],
          ...Object.entries(record?.hashes || {}).map(([algorithm, digest]) => [`${algorithm} 哈希`, digest]),
        ].filter(([, value]) => value !== null && value !== undefined && value !== '');

        return (
          <article
            key={record?.record_id || `${title}-${index}`}
            data-record-id={record?.record_id}
            className="scroll-mt-24 rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/70"
          >
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
            <div className="mt-2"><RecordBadges record={record} /></div>
            {properties.length > 0 && (
              <dl className="mt-4 grid gap-x-5 gap-y-2 sm:grid-cols-2">
                {properties.map(([name, value]) => (
                  <div key={name} className="min-w-0">
                    <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{name}</dt>
                    <dd className="break-words text-sm text-slate-700 dark:text-slate-200">{displayValue(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <AttachmentList attachments={record?.attachments} />
          </article>
        );
      })}
    </div>
  );
}

KeyValueRenderer.displayName = 'KeyValueRenderer';
