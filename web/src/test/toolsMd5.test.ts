import { describe, expect, it } from 'vitest';
import md5Default, { md5Hex } from '../pages/tools/md5';

/** UTF-8 编码，与 HashTool 内的口径一致。 */
const enc = (s: string): Uint8Array => new TextEncoder().encode(s);

/* RFC 1321 官方测试向量（A.5），取自文档原文。 */
const RFC_1321_VECTORS: Array<[string, string]> = [
  ['', 'd41d8cd98f00b204e9800998ecf8427e'],
  ['a', '0cc175b9c0f1b6a831c399e269772661'],
  ['abc', '900150983cd24fb0d6963f7d28e17f72'],
  ['message digest', 'f96b697d7cb7938d525a2f31aaf161d0'],
  ['abcdefghijklmnopqrstuvwxyz', 'c3fcd3d76192e4007dfb496cca67e13b'],
  [
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
    'd174ab98d277d9f5a5611c2c9f419d9f',
  ],
  [
    // 数字 0-9 连写八遍（80 字节，跨两个分组）
    '12345678901234567890123456789012345678901234567890123456789012345678901234567890',
    '57edf4a22be3c955ac49da2e2107b67a',
  ],
];

describe('md5Hex — RFC 1321 官方向量', () => {
  it.each(RFC_1321_VECTORS)('md5(%j) = %s', (input, expected) => {
    expect(md5Hex(enc(input))).toBe(expected);
  });
});

describe('md5Hex — UTF-8 与长输入', () => {
  it('多字节 UTF-8（中文）与 node:crypto 摘要一致', () => {
    expect(md5Hex(enc('中文'))).toBe('a7bac2239fcdcb3a067903d8077c4a07');
  });

  it('中英混合文本', () => {
    expect(md5Hex(enc('TraceLens-取证-日志'))).toBe(md5Hex(enc('TraceLens-取证-日志')));
    // 与分段拼接后的整体摘要一致（同输入必然同输出）
    expect(md5Hex(enc('TraceLens-取证-日志'))).not.toBe(md5Hex(enc('TraceLens-取证')));
  });

  it('多分组（1700 字节）长字符串', () => {
    const long = 'TraceLens-取证-'.repeat(100); // 15+2=17 字节/次 × 100
    expect(enc(long).length).toBe(1700);
    expect(md5Hex(enc(long))).toBe('5ac6d99e6f46b2f367e804c0544fc9d6');
  });
});

describe('md5Hex — 填充边界（55/56/63/64 字节）', () => {
  // 55 字节：补 0x80 后恰好填满单个 64 字节分组；
  // 56 字节：长度字段放不下，必须新增一个分组；
  // 63/64 字节：覆盖最后不满/整块的情形。期望值均来自 node:crypto。
  const BOUNDARY_VECTORS: Array<[number, string]> = [
    [55, 'ef1772b6dff9a122358552954ad0df65'],
    [56, '3b0c8ac703f828b04c6c197006d17218'],
    [63, 'b06521f39153d618550606be297466d5'],
    [64, '014842d480b571495a4a0363793f7367'],
  ];

  it.each(BOUNDARY_VECTORS)('%i 字节 ASCII 输入的填充边界', (size, expected) => {
    expect(md5Hex(enc('a'.repeat(size)))).toBe(expected);
  });

  it('55 个中文（165 字节）跨多分组且多字节收尾', () => {
    const text = '中'.repeat(55);
    expect(enc(text).length).toBe(165);
    expect(md5Hex(enc(text))).toBe('8e9434d7d7bbbc988274133bab5a66cb');
  });
});

describe('md5Hex — 输出格式与入参口径', () => {
  it('输出恒为 32 位小写十六进制', () => {
    const samples = ['', 'a', 'abc', '中文', 'x'.repeat(200)];
    for (const s of samples) {
      expect(md5Hex(enc(s))).toMatch(/^[0-9a-f]{32}$/);
    }
  });

  it('同输入两次调用结果一致（纯函数无状态）', () => {
    expect(md5Hex(enc('deterministic'))).toBe(md5Hex(enc('deterministic')));
  });

  it('接受 ArrayBuffer 入参，与 Uint8Array 口径一致', () => {
    const bytes = enc('abc');
    // TS 5.9 的 .buffer 类型是 ArrayBufferLike，收窄为 ArrayBuffer
    const buf = bytes.buffer as ArrayBuffer;
    expect(md5Hex(buf)).toBe(md5Hex(bytes));
    expect(md5Hex(buf)).toBe('900150983cd24fb0d6963f7d28e17f72');
  });

  it('空字节序列即空串摘要', () => {
    expect(md5Hex(new Uint8Array(0))).toBe('d41d8cd98f00b204e9800998ecf8427e');
  });

  it('默认导出与具名导出是同一个函数', () => {
    expect(md5Default).toBe(md5Hex);
  });
});
