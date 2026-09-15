import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import Card, { CardHeader } from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { Segmented } from '../../components/ui/PageScaffold';
import { ResultRow } from './shared';

/* ---------------------------------------------------------------------------
 * 进制 / 编码转换：文本与 Hex / Base64 / Base64URL / URL 互转。
 * 统一以 UTF-8 字节为中间口径（TextEncoder / TextDecoder），中文不乱码；
 * 同一输入同时给出「编码」与「解码」两个方向的结果，输入变即算。
 * ------------------------------------------------------------------------- */

const CODECS = [
  { value: 'hex', label: 'Hex' },
  { value: 'base64', label: 'Base64' },
  { value: 'base64url', label: 'Base64URL' },
  { value: 'url', label: 'URL' },
] as const;

type CodecId = (typeof CODECS)[number]['value'];

const utf8Bytes = (text: string): Uint8Array => new TextEncoder().encode(text);

function base64Encode(bytes: Uint8Array): string {
  let bin = '';
  const CHUNK = 0x8000; // 分块展开，避免超长数组触发调用栈上限
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

function base64Decode(b64: string): string {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

function encodeWith(text: string, codec: CodecId): string {
  switch (codec) {
    case 'hex':
      return Array.from(utf8Bytes(text), (b) => b.toString(16).padStart(2, '0')).join('');
    case 'base64':
      return base64Encode(utf8Bytes(text));
    case 'base64url':
      return base64Encode(utf8Bytes(text)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    case 'url':
      return encodeURIComponent(text);
  }
}

/** 解码失败（格式非法）返回 null。 */
function decodeWith(text: string, codec: CodecId): string | null {
  try {
    switch (codec) {
      case 'hex': {
        const clean = text.replace(/\s+/g, '');
        if (clean.length === 0 || clean.length % 2 !== 0 || /[^0-9a-fA-F]/.test(clean)) return null;
        const bytes = new Uint8Array(clean.length / 2);
        for (let i = 0; i < bytes.length; i += 1) bytes[i] = Number.parseInt(clean.slice(i * 2, i * 2 + 2), 16);
        return new TextDecoder().decode(bytes);
      }
      case 'base64':
        return base64Decode(text.replace(/\s+/g, ''));
      case 'base64url': {
        let s = text.replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
        while (s.length % 4 !== 0) s += '=';
        return base64Decode(s);
      }
      case 'url':
        return decodeURIComponent(text);
    }
  } catch {
    return null;
  }
}

const codecLabel = (id: CodecId): string => CODECS.find((c) => c.value === id)?.label ?? id;

export default function EncodeTool() {
  const [text, setText] = useState('');
  const [codec, setCodec] = useState<CodecId>('base64');

  const byteLen = useMemo(() => (text ? utf8Bytes(text).length : 0), [text]);
  const encoded = useMemo(() => (text ? encodeWith(text, codec) : ''), [text, codec]);
  const decoded = useMemo(() => (text ? decodeWith(text, codec) : null), [text, codec]);

  return (
    <Card>
      <CardHeader
        title="编码转换"
        subtitle="文本与 Hex / Base64 / Base64URL / URL 互转，UTF-8 口径，双向同屏"
        actions={
          <Button variant="ghost" size="sm" onClick={() => setText('')}>
            <Trash2 size={13} />
            清空
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Segmented options={CODECS.map((c) => ({ value: c.value, label: c.label }))} value={codec} onChange={setCodec} />
        {text && (
          <span className="text-2xs tabular-nums text-ink-400 dark:text-ink-500">
            输入 {text.length} 字符 / UTF-8 {byteLen} 字节
          </span>
        )}
      </div>

      <label className="field-label" htmlFor="encode-input">输入（编码或解码内容均可，自动双向转换）</label>
      <textarea
        id="encode-input"
        className="input font-mono text-xs leading-relaxed"
        rows={4}
        spellCheck={false}
        placeholder="输入文本，或粘贴上面的编码结果自动解码"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="mt-3">
        <ResultRow label={`编码 ${codecLabel(codec)}`} value={encoded} emptyValue="输入内容后自动编码" />
        <ResultRow label={`解码 ${codecLabel(codec)}`} value={decoded ?? ''} emptyValue={text ? '不是有效的编码' : '输入内容后自动解码'} />
      </div>
      {text && decoded === null && (
        <p className="mt-1.5 text-2xs text-amber-600 dark:text-amber-400">
          当前输入无法按 {codecLabel(codec)} 解码：请检查格式（Hex 需偶数个 0-9a-f 字符，Base64 需 4 的倍数长度）。
        </p>
      )}

      <p className="mt-3 text-2xs leading-relaxed text-ink-400 dark:text-ink-500">
        文本统一按 UTF-8 编码后再转 Hex / Base64（中文占 3 字节）；Base64URL 使用 - _ 字符且省略填充；
        URL 编码为 encodeURIComponent 口径。粘贴编码内容即可反向解码出原文。
      </p>
    </Card>
  );
}
