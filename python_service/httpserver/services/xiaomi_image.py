"""Bounded read-only reader for exported Android EXT4 images with DMF/data/storage.

This recognizes the export layout, not an OEM signature. Directory padding may
end at i_size; extent overlaps are NEVER reinterpreted or filled with zeros.
Only index metadata goes through stdout. Evidence code is never executed.
"""
from __future__ import annotations
import hashlib
import json
import mmap
import os
from pathlib import Path
import stat
import struct
import sys
from urllib.parse import quote_from_bytes

VERSION = 'xiaomi-export-ext4-v1'
MAX_ENTRIES = 500_000
MAX_FILE = 8 << 30


class ImageError(ValueError):
    pass


class ExportImage:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.fd = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        self.mm = None
        self.directory_warnings = {}
        try:
            self.identity = os.fstat(self.fd)
            self.path_identity = os.stat(self.path, follow_symlinks=False)
            if not stat.S_ISREG(self.identity.st_mode) or self.identity.st_size < 4096:
                raise ImageError('不是有效的普通镜像文件')
            self.mm = mmap.mmap(self.fd, 0, access=mmap.ACCESS_READ)
            sb = self.read(1024, 1024)
            if struct.unpack_from('<H', sb, 56)[0] != 0xef53:
                raise ImageError('不是受支持的 EXT4 导出镜像')
            self.features = struct.unpack_from('<I', sb, 96)[0]
            # Extents, filetype, 64-bit, flex_bg and checksum_seed. Refuse unknown layouts.
            if self.features & ~0x22c2:
                raise ImageError('文件系统含未支持或加密特性')
            shift = struct.unpack_from('<I', sb, 24)[0]
            if shift > 2: raise ImageError('文件系统块大小不受支持')
            self.bs = 1024 << shift
            self.inodes = struct.unpack_from('<I', sb, 0)[0]
            self.ipg = struct.unpack_from('<I', sb, 40)[0]
            self.isz = struct.unpack_from('<H', sb, 88)[0]
            self.dsz = struct.unpack_from('<H', sb, 254)[0] if self.features & 128 else 32
            self.gdt = (struct.unpack_from('<I', sb, 20)[0] + 1) * self.bs
            blocks = struct.unpack_from('<I', sb, 4)[0]
            if self.features & 128: blocks |= struct.unpack_from('<I', sb, 336)[0] << 32
            if not self.ipg or not self.inodes or not 128 <= self.isz <= self.bs or not 32 <= self.dsz <= self.bs:
                raise ImageError('文件系统元数据无效')
            self.size = blocks * self.bs
            if self.size != self.identity.st_size:
                raise ImageError('镜像长度与文件系统声明不一致')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.mm is not None: self.mm.close(); self.mm = None
        if self.fd is not None: os.close(self.fd); self.fd = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.mm) or size > len(self.mm) - offset:
            raise ImageError('文件区段超出镜像边界')
        return self.mm[offset:offset + size]

    def inode(self, number):
        if not 1 <= number <= self.inodes: raise ImageError('inode 超出有效范围')
        group, index = divmod(number - 1, self.ipg)
        desc = self.read(self.gdt + group * self.dsz, self.dsz)
        block = struct.unpack_from('<I', desc, 8)[0]
        if self.features & 128:
            if self.dsz < 64: raise ImageError('无效的 64 位组描述符')
            block |= struct.unpack_from('<I', desc, 40)[0] << 32
        offset = block * self.bs + index * self.isz
        return offset, self.read(offset, self.isz)

    def details(self, number):
        offset, raw = self.inode(number)
        mode = struct.unpack_from('<H', raw, 0)[0]
        size = struct.unpack_from('<I', raw, 4)[0] | struct.unpack_from('<I', raw, 108)[0] << 32
        return {'inode': number, 'inode_offset': offset, 'inode_size': self.isz,
                'inode_sha256': hashlib.sha256(raw).hexdigest(), 'mode': mode,
                'size': size, 'source_mtime': struct.unpack_from('<I', raw, 16)[0],
                'flags': struct.unpack_from('<I', raw, 32)[0]}, raw

    def runs(self, raw):
        flags = struct.unpack_from('<I', raw, 32)[0]
        if flags & 0x10000800: raise ImageError('加密或内联文件未支持')
        if not flags & 0x80000: raise ImageError('非 extent 文件布局未支持')
        runs, visited = [], set()
        def walk(buf, expected=None, level=0):
            if level > 5 or len(buf) < 12: raise ImageError('extent 树深度或长度无效')
            magic, count, maximum, depth = struct.unpack_from('<4H', buf)
            if magic != 0xf30a or depth > 5 or (expected is not None and depth != expected) or count > maximum or 12 + count * 12 > len(buf):
                raise ImageError('extent 树元数据无效')
            previous = -1
            for i in range(count):
                at = 12 + i * 12
                logical = struct.unpack_from('<I', buf, at)[0]
                if logical <= previous: raise ImageError('extent 记录无序或重复')
                previous = logical
                if depth:
                    block = struct.unpack_from('<I', buf, at + 4)[0] | struct.unpack_from('<H', buf, at + 8)[0] << 32
                    if block in visited: raise ImageError('extent 树存在循环')
                    visited.add(block)
                    walk(self.read(block * self.bs, self.bs), depth - 1, level + 1)
                else:
                    length = struct.unpack_from('<H', buf, at + 4)[0]
                    uninit = length > 0x8000
                    count_blocks = length - 0x8000 if uninit else length
                    physical = struct.unpack_from('<I', buf, at + 8)[0] | struct.unpack_from('<H', buf, at + 6)[0] << 32
                    if not count_blocks or physical == 0 or physical * self.bs + count_blocks * self.bs > self.size:
                        raise ImageError('extent 区段越界或长度无效')
                    runs.append([logical * self.bs, -1 if uninit else physical * self.bs, count_blocks * self.bs])
                    if len(runs) > 100_000: raise ImageError('extent 数量超限')
        walk(raw[40:100])
        runs.sort()
        end = 0
        for logical, _, length in runs:
            if logical < end: raise ImageError('extent 逻辑区段重叠，未尝试重排或修复')
            end = logical + length
        return runs

    def directory(self, number, partial=False):
        info, raw = self.details(number)
        if info['mode'] & 0xf000 != 0x4000 or info['size'] > 64 << 20:
            raise ImageError('目录类型或大小无效')
        out, names, pos = [], set(), 0
        ambiguous = set()
        def invalid(message):
            if not partial: raise ImageError(message)
            self.directory_warnings[number] = message + '；仅保留已验证的目录项'
        for logical, physical, length in self.runs(raw):
            if logical != pos or physical < 0: raise ImageError('目录含空洞或未初始化区段')
            for delta in range(0, length, self.bs):
                remain = info['size'] - logical - delta
                if remain <= 0: break
                block = self.read(physical + delta, min(remain, self.bs))
                at = 0
                while at < len(block):
                    if not any(block[at:]): break  # export's explicit zero padding
                    if at + 8 > len(block): invalid('目录项截断'); break
                    child, rec, nlen, kind = struct.unpack_from('<IHBB', block, at)
                    if rec < 8 or rec % 4 or at + rec > len(block) or nlen > rec - 8:
                        invalid('目录项长度或边界无效'); break
                    name = block[at + 8:at + 8 + nlen]; at += rec
                    if not child or name in (b'.', b'..'): continue
                    if not name or b'/' in name or b'\0' in name or child > self.inodes:
                        invalid('目录项名称或 inode 无效'); continue
                    if name in names or name in ambiguous:
                        invalid('目录内存在重复名称'); ambiguous.add(name)
                        out = [(n, i) for n, i in out if n != name]
                        continue
                    names.add(name); out.append((name, child))
                    if len(out) > MAX_ENTRIES: raise ImageError('目录项数量超限')
            pos = logical + length
        if pos < info['size']: raise ImageError('目录数据不足')
        return out

    def probe(self):
        root = dict(self.directory(2))
        if not all(name in root for name in (b'DMF', b'data', b'storage')):
            raise ImageError('不是 DMF 手机数据导出镜像布局')
        if not any(name.lower().endswith(b'.dmf') for name, _ in self.directory(root[b'DMF'])):
            raise ImageError('缺少 DMF 导出标识文件')
        return {'kind': 'xiaomi_export_image', 'adapter': 'xiaomi-image', 'size': self.size,
                'filesystem': 'ext4', 'partition_offset': 0, 'reader': VERSION,
                'layout': 'dmf_export', 'vendor_verified': False}

    def unchanged(self):
        current = os.stat(self.path, follow_symlinks=False)
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        # Windows exposes creation/change time differently through fstat/stat.
        # Compare each API with its own initial snapshot, plus the open descriptor.
        if (any(getattr(current, k) != getattr(self.path_identity, k) for k in keys) or
                any(getattr(os.fstat(self.fd), k) != getattr(self.identity, k) for k in keys)):
            raise ImageError('来源镜像在读取期间发生变化')

    def index(self, emit):
        meta = self.probe()
        digest = hashlib.sha256()
        for offset in range(0, self.size, 8 << 20):
            digest.update(self.mm[offset:offset + (8 << 20)])
            if offset % (256 << 20) == 0: emit({'type': 'progress', 'bytes': offset})
        meta.update(source_sha256=digest.hexdigest(), platform='Android / MIUI', device='',
                    adapter_version=VERSION, source_path=str(self.path), block_size=self.bs,
                    source_identity={key: getattr(self.path_identity, key) for key in
                                     ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
        emit({'type': 'meta', 'manifest': meta})
        queue, seen_dirs, count, warnings = [(b'', 2, 0)], set(), 0, 0
        while queue:
            prefix, number, depth = queue.pop()
            if depth > 63: raise ImageError('目录深度超限')
            if number in seen_dirs:
                emit({'type': 'warning', 'path': '/' + quote_from_bytes(prefix, safe='/._-'),
                      'detail': '目录循环或目录硬链接，未重复遍历'}); continue
            seen_dirs.add(number)
            try: children = self.directory(number, partial=number != 2)
            except ImageError as exc:
                if number == 2: raise
                warnings += 1
                if warnings > 10000: raise ImageError('不可读目录过多')
                emit({'type': 'warning', 'path': '/' + quote_from_bytes(prefix, safe='/._-'),
                      'detail': str(exc)}); continue
            if number in self.directory_warnings:
                warnings += 1
                emit({'type': 'warning', 'path': '/' + quote_from_bytes(prefix, safe='/._-'),
                      'detail': self.directory_warnings[number]})
                if warnings > 10000: raise ImageError('不可读目录过多')
            for name, child in children:
                count += 1
                if count > MAX_ENTRIES: raise ImageError('来源索引数量超限')
                path = prefix + b'/' + name if prefix else name
                if len(path) > 4096: raise ImageError('来源路径过长')
                info, raw = self.details(child)
                kind = info['mode'] & 0xf000
                if kind == 0x4000: queue.append((path, child, depth + 1)); continue
                encoded = '/' + quote_from_bytes(path, safe='/._-')
                if kind != 0x8000:
                    emit({'type': 'warning', 'path': encoded, 'detail': '未跟随符号链接或特殊文件'}); continue
                parts = path.split(b'/')
                package = parts[1].decode('ascii', errors='replace') if len(parts) > 2 and parts[0] == b'data' else ''
                if not package or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._' for c in package): package = ''
                info.update(type='file', path=encoded, package=package, runs=[], readable=True, error='')
                try:
                    if info['size'] > MAX_FILE: raise ImageError('文件超过单文件读取上限')
                    info['runs'] = self.runs(raw)
                except ImageError as exc: info.update(readable=False, error=str(exc))
                emit(info)
        self.unchanged()
        emit({'type': 'complete', 'entries': count, 'directories': len(seen_dirs), 'warnings': warnings})


def inspect_header(path):
    try:
        with ExportImage(path) as source: return {'candidate': True, **source.probe()}
    except (OSError, ValueError, struct.error, OverflowError): return {'candidate': False}


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ('probe', 'index'): raise ImageError('读取器命令无效')
        emit = lambda obj: print(json.dumps(obj, ensure_ascii=True, separators=(',', ':')), flush=True)
        with ExportImage(sys.argv[2]) as source:
            if sys.argv[1] == 'probe': emit({'type': 'probe', **source.probe()})
            else: source.index(emit)
    except Exception as exc:
        print(json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=True), flush=True)
        raise SystemExit(2)
