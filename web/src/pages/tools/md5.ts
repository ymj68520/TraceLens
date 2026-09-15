/* ---------------------------------------------------------------------------
 * MD5（RFC 1321）纯 JS 实现。
 * Web Crypto 的 crypto.subtle 不提供 MD5，而取证场景（已知文件指纹、
 * 历史库比对）仍依赖 MD5，故在此自带一份与 RFC 一致的实现。
 * 已对空串、RFC 1321 测试向量、55/56/63/64 字节填充边界、多字节 UTF-8
 * 与多分组长输入逐一与 node:crypto 比对通过。
 * ------------------------------------------------------------------------- */

const K = new Int32Array(64);
for (let i = 0; i < 64; i += 1) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32);

const SHIFTS = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];

const rotl = (x: number, c: number): number => (x << c) | (x >>> (32 - c));

/** 计算任意字节序列的 MD5，返回 32 位小写十六进制字符串。 */
export function md5Hex(input: Uint8Array | ArrayBuffer): string {
  const data = input instanceof Uint8Array ? input : new Uint8Array(input);
  const len = data.length;
  const paddedLen = Math.ceil((len + 9) / 64) * 64;
  const buf = new Uint8Array(paddedLen);
  buf.set(data);
  buf[len] = 0x80;
  // 64 位小端比特长度（拆成两个 32 位写入，>512MB 的文件也不会溢出）
  const view = new DataView(buf.buffer);
  view.setUint32(paddedLen - 8, (len % 536870912) * 8, true);
  view.setUint32(paddedLen - 4, Math.floor(len / 536870912), true);

  let a0 = 0x67452301 | 0;
  let b0 = 0xefcdab89 | 0;
  let c0 = 0x98badcfe | 0;
  let d0 = 0x10325476 | 0;

  const words = new Int32Array(16);
  for (let off = 0; off < paddedLen; off += 64) {
    for (let j = 0; j < 16; j += 1) words[j] = view.getInt32(off + j * 4, true);
    let a = a0;
    let b = b0;
    let c = c0;
    let d = d0;
    for (let i = 0; i < 64; i += 1) {
      let f: number;
      let g: number;
      if (i < 16) {
        f = (b & c) | (~b & d);
        g = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        g = (5 * i + 1) % 16;
      } else if (i < 48) {
        f = b ^ c ^ d;
        g = (3 * i + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        g = (7 * i) % 16;
      }
      f = (f + a + K[i] + words[g]) | 0;
      a = d;
      d = c;
      c = b;
      b = (b + rotl(f, SHIFTS[(i >> 4) * 4 + (i & 3)])) | 0;
    }
    a0 = (a0 + a) | 0;
    b0 = (b0 + b) | 0;
    c0 = (c0 + c) | 0;
    d0 = (d0 + d) | 0;
  }

  const out = new Uint8Array(16);
  const outView = new DataView(out.buffer);
  outView.setInt32(0, a0, true);
  outView.setInt32(4, b0, true);
  outView.setInt32(8, c0, true);
  outView.setInt32(12, d0, true);
  return Array.from(out, (x) => x.toString(16).padStart(2, '0')).join('');
}

export default md5Hex;
