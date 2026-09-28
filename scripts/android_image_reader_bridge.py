"""Strict JSON/NDJSON, read-only bridge to pinned qnxprobe 1.34.

The source image is never mounted or opened writable. The bridge is intentionally
small: discovery and exact inode reads only. No untrusted Python/JS is executed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import sys

PINNED = {
    "qnxprobe.py": "ab0f681313bc305f3662d4421199f45da357da3becf90b28696a158fbaae2710",
    "ewfprobe.py": "304616fcdd362339c6890a100eeaba824822f518a09831eb50ed75692f3e52b8",
}
VERSION = "qnxprobe-1.34-fc74ca829c27"
MAX_ENTRIES = 1_000_000
MAX_FILE_BYTES = 8 * 1024**3


def _reader():
    root = Path(os.environ.get("TRACELENS_QNXPROBE_ROOT") or
                Path(__file__).resolve().parent.parent / ".deps/qnxprobe").resolve()
    for name, expected in PINNED.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("QNXPROBE_PIN_MISMATCH")
    sys.path.insert(0, str(root))
    import qnxprobe  # type: ignore[import-not-found]
    return qnxprobe


def _volumes(qp, image):
    with qp.open_image(image) as handle:
        for vol in qp.volumes(handle):
            yield {
                "base": vol["base"], "size": vol["size"],
                "kind": vol["kind"], "label": vol["label"],
                "name": vol["name"], "readable": bool(vol.get("walker")),
                "note": vol.get("note", ""),
                "missing_past_end": vol.get("missing_past_end", 0),
            }


def _segment_count(qp, image):
    if not qp.looks_like_ewf(image):
        return 1
    with qp.open_image(image) as handle:
        return len(handle.paths)


def _inspect(qp, image):
    output = []
    with qp.open_image(image) as handle:
        for vol in qp.volumes(handle):
            item = {"base": vol["base"], "size": vol["size"],
                    "kind": vol["kind"], "label": vol["label"],
                    "name": vol["name"], "readable": bool(vol.get("walker")),
                    "note": vol.get("note", ""),
                    "missing_past_end": vol.get("missing_past_end", 0)}
            walker = vol.get("walker")
            if walker and vol["kind"] in {"ext4", "f2fs"}:
                markers = []
                fstab_flags = []
                regular = readable = encrypted = 0
                encrypted_dirs = set()
                if vol["kind"] == "f2fs":
                    root = walker.inode(walker.root)
                    if root and walker._encrypted(root):
                        encrypted_dirs.add("")
                for path, inode, mode, size, _, _ in qp.walk_all(walker):
                    if path.count("/") >= 63:
                        raise RuntimeError("FILESYSTEM_DEPTH_LIMIT")
                    raw = walker.inode(inode)
                    inode_encrypted = bool(raw and (walker._encrypted(raw) if vol["kind"] == "f2fs"
                        else int.from_bytes(raw[32:36], "little") & 0x00000800))
                    if inode_encrypted and (mode & 0o170000) == 0o040000:
                        encrypted_dirs.add(path)
                    if (mode & 0o170000) != 0o100000:
                        continue
                    regular += 1
                    parent = path.rpartition("/")[0]
                    name_unavailable = (parent in encrypted_dirs or
                                        any(parent.startswith(d + "/") for d in encrypted_dirs if d))
                    locked = bool(inode_encrypted or name_unavailable)
                    encrypted += int(locked)
                    readable += int(not locked)
                    if not name_unavailable and (path.startswith(("data/com.", "user/0/com.", "user_de/0/com.",
                                        "data/data/com.", "data/user/0/com.")) or path in (
                                            "system/packages.xml", "misc/wifi/WifiConfigStore.xml")):
                        if len(markers) < 50:
                            markers.append(path)
                    if (not locked and size is not None and 0 < size <= 1024 * 1024 and
                        (path.startswith(("etc/fstab.", "system/etc/fstab.", "vendor/etc/fstab.")) or
                         path in ("fstab", "etc/fstab"))):
                        try:
                            content = b"".join(walker.read_file(inode, size))
                            if len(content) == size and b"metadata_encryption=" in content:
                                fstab_flags.append("metadata_encryption")
                            if len(content) == size and b"fileencryption=" in content:
                                fstab_flags.append("fileencryption")
                        except Exception:
                            pass  # no assertion from a file that could not be read
                    if regular > MAX_ENTRIES:
                        raise RuntimeError("IMAGE_INDEX_LIMIT")
                features = getattr(walker, "feature", None)
                if vol["kind"] == "ext4":
                    raw_features = qp.read_at(handle, vol["base"] + 1024 + 96, 4)
                    features = struct.unpack("<I", raw_features)[0] if len(raw_features) == 4 else None
                item.update({"android_markers": markers, "regular_files": regular,
                             "readable_files": readable, "encrypted_files": encrypted,
                             "feature_flags": features, "fstab_flags": sorted(set(fstab_flags))})
            output.append(item)
    return output


def _walker(qp, handle, base, kind="f2fs"):
    for vol in qp.volumes(handle):
        if vol["base"] == base and vol["kind"] == kind:
            walker = vol.get("walker")
            if walker is None:
                raise RuntimeError("FILESYSTEM_UNREADABLE")
            return walker
    raise RuntimeError("FILESYSTEM_VOLUME_NOT_FOUND")


def _list(qp, handle, base, kind="f2fs"):
    walker = _walker(qp, handle, base, kind)
    count = 0
    root_inode = walker.inode(walker.root)
    root_encrypted = bool(root_inode and (walker._encrypted(root_inode) if kind == "f2fs"
        else int.from_bytes(root_inode[32:36], "little") & 0x00000800))
    encrypted_directories = {""} if root_encrypted else set()
    for path, inode, mode, size, mtime, _ in qp.walk_all(walker):
        if path.count("/") >= 63:
            raise RuntimeError("FILESYSTEM_DEPTH_LIMIT")
        if (mode & 0o170000) not in (0o100000, 0o040000):
            continue  # symlinks and special files are not followed or indexed
        count += 1
        if count > MAX_ENTRIES:
            raise RuntimeError("F2FS_INDEX_LIMIT")
        parent = path.rpartition("/")[0]
        unavailable = (parent in encrypted_directories or
                       any(parent.startswith(directory + "/") for directory in encrypted_directories if directory))
        if not isinstance(path, str) or len(path) > 4096 or "\ufffd" in path or unavailable:
            # Do not invent a filename from an undecodable FBE dentry.
            print(json.dumps({"status": "NAME_ENCRYPTED_OR_UNAVAILABLE", "inode": inode,
                              "name_state": "encrypted_or_unavailable"}), flush=True)
            continue
        raw = walker.inode(inode)
        encrypted = bool(raw and (walker._encrypted(raw) if kind == "f2fs"
            else int.from_bytes(raw[32:36], "little") & 0x00000800))
        if encrypted and (mode & 0o170000) == 0o040000:
            encrypted_directories.add(path)
        compressed = bool(raw and walker._compressed(raw)) if kind == "f2fs" else False
        created, modified, accessed = walker.stamps(inode) if kind == "f2fs" else (0, mtime, 0)
        print(json.dumps({"path": path, "inode": inode, "size": size,
                          "mode": mode, "mtime": modified or mtime,
                          "ctime": created, "atime": accessed,
                          "encrypted": encrypted, "compressed": compressed,
                          "name_state": "clear"}, ensure_ascii=True), flush=True)
    print(json.dumps({"status": "END", "count": count, "feature_flags": getattr(walker, "feature", None),
                      "reader": VERSION}), flush=True)


def _extract(qp, handle, base, inode, size, output):
    if inode < 0 or size < 0 or size > MAX_FILE_BYTES:
        raise RuntimeError("INVALID_FILE_REQUEST")
    walker = _walker(qp, handle, base)
    entry = walker.entry(inode)
    if not entry or entry[1] != size or (entry[0] & 0o170000) != 0o100000:
        raise RuntimeError("FILE_METADATA_CHANGED")
    raw = walker.inode(inode)
    if raw and walker._encrypted(raw):
        raise RuntimeError("ENCRYPTED_FILE")
    if raw and walker._compressed(raw):
        raise RuntimeError("UNSUPPORTED_F2FS_COMPRESSION")
    # C++ provides an internal, evidence-disjoint temporary path; O_EXCL avoids
    # overwriting a symlink or preexisting file. Failed reads remove partials.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    total = 0
    try:
        with os.fdopen(fd, "wb") as sink:
            for chunk in walker.read_file(inode, size):
                total += len(chunk)
                if total > size:
                    raise RuntimeError("FILE_OVERREAD")
                sink.write(chunk)
            sink.flush()
            os.fsync(sink.fileno())
        if total != size:
            raise RuntimeError("FILE_SHORT_READ")
    except Exception:
        Path(output).unlink(missing_ok=True)
        raise
    print(json.dumps({"status": "OK", "bytes": total, "reader": VERSION}))


def main(argv):
    if len(argv) not in (3, 4, 7) or argv[1] not in ("probe", "inspect", "list", "list-ext4", "extract"):
        raise RuntimeError("INVALID_COMMAND")
    command, image = argv[1:3]
    if not Path(image).is_file():
        raise RuntimeError("IMAGE_NOT_FOUND")
    qp = _reader()
    if command == "probe" and len(argv) == 3:
        print(json.dumps({"status": "OK", "reader": VERSION,
                          "container": "e01" if qp.looks_like_ewf(image) else "raw",
                          "segment_count": _segment_count(qp, image),
                          "volumes": list(_volumes(qp, image))}))
        return
    if command == "inspect" and len(argv) == 3:
        print(json.dumps({"status": "OK", "reader": VERSION,
                          "container": "e01" if qp.looks_like_ewf(image) else "raw",
                          "segment_count": _segment_count(qp, image),
                          "volumes": _inspect(qp, image)}))
        return
    if command == "list" and len(argv) == 4:
        with qp.open_image(image) as handle:
            _list(qp, handle, int(argv[3]))
        return
    if command == "list-ext4" and len(argv) == 4:
        with qp.open_image(image) as handle:
            _list(qp, handle, int(argv[3]), "ext4")
        return
    if command == "extract" and len(argv) == 7:
        with qp.open_image(image) as handle:
            _extract(qp, handle, int(argv[3]), int(argv[4]), int(argv[5]), argv[6])
        return
    raise RuntimeError("INVALID_COMMAND")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "code": str(exc).split(":", 1)[0][:120]}), file=sys.stderr)
        raise SystemExit(2)
