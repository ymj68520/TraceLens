import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadCSV, downloadJSON, downloadText } from '../lib/exportUtils';

interface CapturedDownload {
  blob: Blob;
  url: string;
  filename: string;
}

/** Each createObjectURL call pushes one entry; the click fills in the filename. */
const downloads: CapturedDownload[] = [];

// jsdom has no URL.createObjectURL/revokeObjectURL, so install fakes on the
// constructor once instead of spying.
const createObjectURLMock = vi.fn((obj: Blob | MediaSource) => {
  const url = `blob:mock-${downloads.length}`;
  downloads.push({ blob: obj as Blob, url, filename: '' });
  return url;
});
const revokeObjectURLMock = vi.fn();

beforeAll(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    value: createObjectURLMock,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: revokeObjectURLMock,
    configurable: true,
    writable: true,
  });
});

beforeEach(() => {
  downloads.length = 0;
  createObjectURLMock.mockClear();
  revokeObjectURLMock.mockClear();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function captureAnchor(
    this: HTMLAnchorElement,
  ) {
    const entry = downloads[downloads.length - 1];
    if (entry) entry.filename = this.download;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function lastDownload(): CapturedDownload {
  const entry = downloads[downloads.length - 1];
  if (!entry) throw new Error('no download was triggered');
  return entry;
}

/** jsdom's Blob lacks .text(); read through FileReader instead.
 *  Note: the UTF-8 decoder strips a leading BOM, so the BOM itself must be
 *  asserted from the raw bytes (see blobBytes). */
function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsText(blob);
  });
}

function blobBytes(blob: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsArrayBuffer(blob);
  });
}

describe('downloadCSV', () => {
  it('prefixes a BOM, joins lines with CRLF and writes a header row', async () => {
    downloadCSV([{ name: '甲', size: 12 }], 'files');
    const { blob, filename, url } = lastDownload();
    // BOM check on raw bytes: EF BB BF is the UTF-8 encoding of U+FEFF.
    const bytes = new Uint8Array(await blobBytes(blob));
    expect(Array.from(bytes.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    expect(await blobText(blob)).toBe(['name,size', '甲,12'].join('\r\n'));
    expect(blob.type).toBe('text/csv;charset=utf-8');
    expect(filename).toBe('files.csv');
    expect(url).toMatch(/^blob:mock-/);
  });

  it('appends the .csv suffix only when missing', () => {
    downloadCSV([{ a: 1 }], 'report.csv');
    expect(lastDownload().filename).toBe('report.csv');
    downloadCSV([{ a: 1 }], 'report');
    expect(lastDownload().filename).toBe('report.csv');
  });

  it('quotes cells containing commas, quotes or newlines, doubling inner quotes', async () => {
    downloadCSV(
      [{ note: 'a,b' }, { note: 'say "hi"' }, { note: 'line1\nline2' }, { note: 'plain' }],
      'esc',
    );
    const lines = (await blobText(lastDownload().blob)).split('\r\n');
    expect(lines[0]).toBe('note');
    expect(lines[1]).toBe('"a,b"');
    expect(lines[2]).toBe('"say ""hi"""');
    expect(lines[3]).toBe('"line1\nline2"');
    expect(lines[4]).toBe('plain');
  });

  it('stringifies values and renders null/undefined as empty cells', async () => {
    downloadCSV([{ n: null, u: undefined, num: 42, bool: false }], 'cells');
    expect(await blobText(lastDownload().blob)).toBe(['n,u,num,bool', ',,42,false'].join('\r\n'));
  });

  it('honours custom headers as a column subset', async () => {
    downloadCSV([{ a: 1, b: 2 }], 'cols', [{ key: 'b', label: '乙' }]);
    expect(await blobText(lastDownload().blob)).toBe(['乙', '2'].join('\r\n'));
  });

  it('skips the download entirely for empty rows', () => {
    downloadCSV([], 'empty');
    expect(downloads).toHaveLength(0);
  });

  it('revokes the object URL after the click', () => {
    downloadCSV([{ a: 1 }], 'revoke');
    expect(revokeObjectURLMock).toHaveBeenCalledWith(downloads[0].url);
  });
});

describe('downloadJSON', () => {
  it('pretty-prints with a two-space indent and appends .json', async () => {
    const data = { id: 1, items: ['a', 'b'] };
    downloadJSON(data, 'result');
    const { blob, filename } = lastDownload();
    const text = await blobText(blob);
    expect(text).toBe(JSON.stringify(data, null, 2));
    expect(JSON.parse(text)).toEqual(data);
    expect(filename).toBe('result.json');
    expect(blob.type).toBe('application/json');
  });

  it('keeps an existing .json suffix', () => {
    downloadJSON({}, 'already.json');
    expect(lastDownload().filename).toBe('already.json');
  });
});

describe('downloadText', () => {
  it('passes raw text through unchanged with the given mime', async () => {
    downloadText('hello', 'note.txt', 'text/foo');
    const { blob, filename } = lastDownload();
    expect(await blobText(blob)).toBe('hello');
    expect(blob.type).toBe('text/foo');
    expect(filename).toBe('note.txt');
  });
});
