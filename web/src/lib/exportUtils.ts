/** Client-side export helpers — CSV/JSON downloads with BOM-safe encoding. */

function triggerDownload(content: BlobPart, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const csvCell = (v: unknown): string => {
  const s = v == null ? '' : String(v);
  // Quote when the cell contains separator/quote/newline; double inner quotes.
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** Rows: array of records; headers default to the first row's keys. */
export function downloadCSV(
  rows: Record<string, unknown>[],
  filename: string,
  headers?: { key: string; label: string }[],
): void {
  if (rows.length === 0) return;
  const cols = headers ?? Object.keys(rows[0]).map((k) => ({ key: k, label: k }));
  const lines = [
    cols.map((c) => csvCell(c.label)).join(','),
    ...rows.map((r) => cols.map((c) => csvCell(r[c.key])).join(',')),
  ];
  // BOM so Excel opens UTF-8 Chinese correctly.
  triggerDownload('\uFEFF' + lines.join('\r\n'), filename.endsWith('.csv') ? filename : `${filename}.csv`, 'text/csv;charset=utf-8');
}

export function downloadJSON(data: unknown, filename: string): void {
  triggerDownload(JSON.stringify(data, null, 2), filename.endsWith('.json') ? filename : `${filename}.json`, 'application/json');
}

export function downloadText(text: string, filename: string, mime = 'text/plain;charset=utf-8'): void {
  triggerDownload(text, filename, mime);
}
