import { useEffect, useRef, useState } from 'react';
import { FileUp, Loader2, Trash2, Upload } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { useToast } from '../../components/ui/Toast';
import { cn, formatBytes } from '../../lib/utils';
import { CopyButton, ResultRow, useDebouncedValue } from './shared';
import { md5Hex } from './md5';

/* ---------------------------------------------------------------------------
 * 哈希计算：文本 / 文件的 MD5、SHA-1、SHA-256、SHA-512。
 * MD5 为本目录 md5.ts 的纯 JS 实现（Web Crypto 不提供）；SHA 系列走
 * crypto.subtle.digest，全部本地计算，无网络请求。
 * ------------------------------------------------------------------------- */

interface HashBundle {
  md5: string;
  sha1: string;
  sha256: string;
  sha512: string;
}

const HASH_ROWS: Array<{ key: keyof HashBundle; label: string; note: string }> = [
  { key: 'md5', label: 'MD5', note: '纯 JS' },
  { key: 'sha1', label: 'SHA-1', note: 'Web Crypto' },
  { key: 'sha256', label: 'SHA-256', note: 'Web Crypto' },
  { key: 'sha512', label: 'SHA-512', note: 'Web Crypto' },
];

const toHex = (buf: ArrayBuffer): string =>
  Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('');

/** SHA-1/256/512 并行摘要；subtle 不可用（非安全上下文）时返回空串。 */
async function shaAll(data: ArrayBuffer | Uint8Array): Promise<Omit<HashBundle, 'md5'>> {
  // 这里的 Uint8Array 均由 TextEncoder / 文件 ArrayBuffer 派生，底层必为 ArrayBuffer
  // （TS 5.9 的 Uint8Array<ArrayBufferLike> 泛型与 BufferSource 不再结构兼容，故收窄一次）。
  const src = data as BufferSource;
  try {
    const [sha1, sha256, sha512] = await Promise.all([
      crypto.subtle.digest('SHA-1', src),
      crypto.subtle.digest('SHA-256', src),
      crypto.subtle.digest('SHA-512', src),
    ]);
    return { sha1: toHex(sha1), sha256: toHex(sha256), sha512: toHex(sha512) };
  } catch {
    return { sha1: '', sha256: '', sha512: '' };
  }
}

const WARN_FILE_BYTES = 16 * 1024 * 1024;
const MAX_FILE_BYTES = 256 * 1024 * 1024;

interface FileHashResult extends HashBundle {
  name: string;
  size: number;
}

export default function HashTool() {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [text, setText] = useState('');
  const debouncedText = useDebouncedValue(text, 250);
  const [textHashes, setTextHashes] = useState<HashBundle | null>(null);

  const [fileResult, setFileResult] = useState<FileHashResult | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  /* 文本哈希：输入防抖后本地计算 */
  useEffect(() => {
    if (!debouncedText) {
      setTextHashes(null);
      return undefined;
    }
    let cancelled = false;
    const bytes = new TextEncoder().encode(debouncedText);
    const md5 = md5Hex(bytes);
    void shaAll(bytes).then((sha) => {
      if (!cancelled) setTextHashes({ md5, ...sha });
    });
    return () => {
      cancelled = true;
    };
  }, [debouncedText]);

  const handleFile = async (file: File) => {
    if (file.size > MAX_FILE_BYTES) {
      toast.error(`文件超过 ${formatBytes(MAX_FILE_BYTES)}，为避免页面卡死已取消计算`);
      return;
    }
    if (file.size > WARN_FILE_BYTES) {
      toast.info(`文件较大（${formatBytes(file.size)}），计算可能需要数秒，期间页面会短暂无响应`);
    }
    setDragOver(false);
    setFileBusy(true);
    try {
      const buf = await file.arrayBuffer();
      const sha = await shaAll(buf);
      setFileResult({ name: file.name, size: file.size, md5: md5Hex(buf), ...sha });
    } catch {
      toast.error('文件读取失败，请重试');
    } finally {
      setFileBusy(false);
    }
  };

  const clearAll = () => {
    setText('');
    setTextHashes(null);
    setFileResult(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <Card>
      <CardHeader
        title="哈希计算"
        subtitle="MD5 / SHA-1 / SHA-256 / SHA-512，输入即算，数据不出浏览器"
        actions={
          <Button variant="ghost" size="sm" onClick={clearAll}>
            <Trash2 size={13} />
            清空
          </Button>
        }
      />

      {/* 文本哈希 */}
      <div>
        <label className="field-label" htmlFor="hash-text">文本输入</label>
        <textarea
          id="hash-text"
          className="input font-mono text-xs leading-relaxed"
          rows={4}
          spellCheck={false}
          placeholder="输入或粘贴文本，实时计算哈希"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="mt-2">
        {textHashes ? (
          HASH_ROWS.map((row) => <ResultRow key={row.key} label={row.label} note={row.note} value={textHashes[row.key]} />)
        ) : (
          <p className="text-xs text-ink-400 dark:text-ink-500">输入文本后在此显示哈希结果</p>
        )}
      </div>

      {/* 文件哈希 */}
      <div className="mt-5 border-t border-ink-100 pt-4 dark:border-ink-800/60">
        <p className="section-label mb-3">文件哈希</p>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          className={cn(
            'rounded-lg border border-dashed px-4 py-6 text-center transition-colors',
            dragOver
              ? 'border-accent-500 bg-accent-50/60 dark:bg-accent-500/10'
              : 'border-ink-300 bg-ink-50/50 dark:border-ink-700 dark:bg-ink-900/40',
          )}
        >
          <Upload size={18} className="mx-auto mb-2 text-ink-400 dark:text-ink-500" strokeWidth={1.8} />
          <p className="text-xs text-ink-500 dark:text-ink-400">拖拽文件到此处计算哈希</p>
          <Button variant="secondary" size="sm" className="mt-3" onClick={() => fileInputRef.current?.click()}>
            <FileUp size={13} />
            选择文件
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
              e.target.value = '';
            }}
          />
        </div>

        {fileBusy && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-500 dark:text-ink-400">
            <Loader2 size={13} className="animate-spin" />
            正在读取并计算…
          </p>
        )}
        {fileResult && !fileBusy && (
          <div className="mt-3">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="chip bg-accent-50 text-accent-700 dark:bg-accent-500/10 dark:text-accent-300">
                {fileResult.name}
              </span>
              <span className="text-2xs tabular-nums text-ink-400 dark:text-ink-500">{formatBytes(fileResult.size)}</span>
              <CopyButton value={fileResult.name} label="文件名" />
            </div>
            {HASH_ROWS.map((row) => (
              <ResultRow key={row.key} label={row.label} note={row.note} value={fileResult[row.key]} />
            ))}
          </div>
        )}
        <p className="mt-3 text-2xs leading-relaxed text-ink-400 dark:text-ink-500">
          MD5 为纯 JS 实现（RFC 1321，与标准实现逐字节比对过）；SHA 系列使用 Web Crypto API，
          需在 localhost 或 HTTPS 下可用（不可用时显示 —）。文件在主线程同步计算，超大文件会短暂占用页面。
        </p>
      </div>
    </Card>
  );
}
