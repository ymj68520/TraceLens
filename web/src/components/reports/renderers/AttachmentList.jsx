function displaySize(size) {
  return Number.isFinite(size) ? `${size.toLocaleString()} B` : null;
}

export default function AttachmentList({ attachments = [] }) {
  if (!attachments.length) return null;

  return (
    <section className="mt-3" aria-label="附件">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">附件</h4>
      <ul className="mt-1 space-y-1 text-sm text-slate-700 dark:text-slate-200">
        {attachments.map((attachment, index) => (
          <li key={attachment?.attachment_id || attachment?.evidence_path || index} className="rounded border border-slate-200 p-2 dark:border-slate-700">
            <p className="break-all font-medium">{attachment?.file_name || attachment?.evidence_path || '未命名附件'}</p>
            {attachment?.evidence_path && <p className="mt-1 break-all font-mono text-xs text-slate-500">{attachment.evidence_path}</p>}
            <p className="mt-1 text-xs text-slate-500">
              {[attachment?.mime, displaySize(attachment?.size)].filter(Boolean).join(' · ')}
              {attachment?.original_included ? ' · 已包含原始文件' : ''}
              {attachment?.unavailable_reason ? ` · ${attachment.unavailable_reason}` : ''}
            </p>
            {Object.entries(attachment?.hashes || {}).map(([algorithm, digest]) => (
              <p key={algorithm} className="mt-1 break-all font-mono text-xs text-slate-500">{algorithm}: {String(digest)}</p>
            ))}
          </li>
        ))}
      </ul>
    </section>
  );
}
