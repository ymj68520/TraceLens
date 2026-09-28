"""Bounded, read-only container inventory for Android logical-source triage.

This does not establish artifact parsing. The C++ Task adapter independently
rechecks all paths and archive limits before AndroidAnalyzer can run.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import io
import os
import re
import secrets
import stat
import tarfile
import time
import zlib
from pathlib import Path

MAX_ENTRIES = 20_000
MAX_SECONDS = 15
MAX_MEMBER_BYTES = 8 * 1024**3
MAX_EXPANDED_BYTES = 2 * 1024**4
MAX_EXPANSION_RATIO = 1_000
NESTED_SUFFIXES = (".zip", ".tar", ".7z", ".img", ".ab", ".e01")


def ab_header(path: Path) -> dict:
    """Read only AOSP's bounded cleartext header; never infer from .ab suffix."""
    try:
        with path.open("rb") as source:
            lines = []
            for _ in range(4):
                line = source.readline(2049)
                if len(line) > 2048 or not line.endswith(b"\n"):
                    return {"kind": "android_backup_unsupported", "reason": "malformed_header"}
                lines.append(line[:-1])
            if lines[0] != b"ANDROID BACKUP":
                return {"kind": "unknown_file", "reason": "missing_ab_magic"}
            if not lines[1].isascii() or not lines[1].isdigit():
                return {"kind": "android_backup_unsupported", "reason": "malformed_version"}
            version = int(lines[1])
            if version not in (1, 2, 3, 4, 5) or lines[2] not in (b"0", b"1"):
                return {"kind": "android_backup_unsupported", "reason": "unsupported_version_or_compression"}
            if lines[3] == b"none":
                return {"kind": "android_backup", "version": version,
                        "compressed": lines[2] == b"1", "payload_offset": source.tell(),
                        "encryption_status": "none"}
            if lines[3] == b"AES-256":
                if version == 1:
                    return {"kind": "android_backup_unsupported", "reason": "legacy_v1_encryption_kdf"}
                extra = []
                for _ in range(5):
                    value = source.readline(2049)
                    if len(value) > 2048 or not value.endswith(b"\n"):
                        return {"kind": "android_backup_unsupported", "reason": "malformed_encryption_header"}
                    extra.append(value[:-1].decode("ascii", errors="strict"))
                if not all(re.fullmatch(r"[0-9a-fA-F]{2,2048}", item) and len(item) % 2 == 0
                           for item in (extra[0], extra[1], extra[3], extra[4])) or not extra[2].isdigit() or len(extra[3]) != 32:
                    return {"kind": "android_backup_unsupported", "reason": "malformed_encryption_header"}
                return {"kind": "android_backup_encrypted", "version": version,
                        "compressed": lines[2] == b"1", "encryption_status": "locked",
                        "payload_offset": source.tell(), "encryption_fields": extra}
            return {"kind": "android_backup_unsupported", "reason": "unsupported_encryption"}
    except (OSError, UnicodeError):
        return {"kind": "android_backup_unsupported", "reason": "unreadable_header"}


def _safe_path(raw: str) -> str:
    if not raw or len(raw) > 4096 or "\x00" in raw or raw.startswith(("//", "\\\\")) or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("RISK_REJECTED: invalid_or_absolute_path")
    absolute = raw.startswith("/")
    value = raw[1:] if absolute else raw
    if value.startswith("./"):
        value = value[2:]
    if "\\" in value or "//" in value or any(part in (".", "..") or len(part) > 255 for part in value.split("/") if part):
        raise ValueError("RISK_REJECTED: unsafe_member_path")
    if absolute and not _android_root(value):
        raise ValueError("RISK_REJECTED: absolute_non_android_path")
    return value


def _android_root(path: str) -> bool:
    return path.startswith(("data/data/", "data/user/0/", "data/user_de/0/", "data/system/", "data/misc/wifi/", "system/app/", "system/priv-app/")) or path == "system/build.prop"


def _android_member(path: str) -> bool:
    return path.startswith(("data/", "system/"))


def _adb_path(path: str) -> str | None:
    match = re.fullmatch(r"apps/([A-Za-z0-9._]{1,255})/(db|f|sp)/(.+)", path)
    if not match:
        return None
    pkg, section, tail = match.groups()
    if pkg in (".", "..") or not any(ch.isalnum() for ch in pkg):
        return None
    kind = {"db": "databases", "f": "files", "sp": "shared_prefs"}[section]
    return f"data/data/{pkg}/{kind}/{tail}"


def root_mapping(raw_paths: list[str], *, android_backup: bool = False) -> dict:
    paths = [_safe_path(value) for value in raw_paths]
    if not paths:
        return {"ready": False, "reason": "no_regular_members"}
    prefixes = {"", "userdata/", "root/"}
    first = paths[0].split("/", 1)
    if len(first) == 2 and all(value.startswith(first[0] + "/") for value in paths):
        prefixes.add(first[0] + "/")
    chosen = max(prefixes, key=lambda prefix: (sum(value.startswith(prefix) and _android_root(value[len(prefix):]) for value in paths), -len(prefix)))
    matches = sum(value.startswith(chosen) and _android_root(value[len(chosen):]) for value in paths)
    adb = android_backup and any(_adb_path(value) for value in paths)
    if not matches and not adb:
        return {"ready": False, "reason": "no_demonstrable_android_root"}
    normalized = set()
    for value in paths:
        target = (value[len(chosen):] if matches and value.startswith(chosen) and _android_member(value[len(chosen):])
                  else _adb_path(value) if android_backup else None)
        if target:
            if target in normalized:
                raise ValueError("RISK_REJECTED: ambiguous_normalized_path")
            normalized.add(target)
    return {"ready": True, "root_mapping": chosen or ("adb_apps" if adb and not matches else "archive_root"),
            "confidence": "medium" if chosen else "high", "reason": "recognized_android_artifact_paths",
            "normalized_count": len(normalized)}


class _ZlibReader(io.RawIOBase):
    def __init__(self, source):
        self.source = source
        self.inflater = zlib.decompressobj()
        self.buffer = bytearray()
        self.pending = b""
        self.finished = False

    def readable(self):
        return True

    def readinto(self, target):
        while len(self.buffer) < len(target) and not self.finished:
            block = self.pending or self.source.read(64 * 1024)
            self.pending = b""
            if not block:
                if not self.inflater.eof:
                    raise zlib.error("truncated Android Backup compressed payload")
                self.finished = True
                self.buffer.extend(self.inflater.flush())
                break
            self.buffer.extend(self.inflater.decompress(block, max(1, len(target) - len(self.buffer))))
            self.pending = self.inflater.unconsumed_tail
            if self.inflater.eof:
                self.finished = True
        amount = min(len(target), len(self.buffer))
        target[:amount] = self.buffer[:amount]
        del self.buffer[:amount]
        return amount


class _AesReader(io.RawIOBase):
    def __init__(self, source, key: bytes, iv: bytes):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7

        self.source = source
        self.decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        self.unpadder = PKCS7(128).unpadder()
        self.buffer = bytearray()
        self.finished = False

    def readable(self):
        return True

    def readinto(self, target):
        while len(self.buffer) < len(target) and not self.finished:
            chunk = self.source.read(64 * 1024)
            if chunk:
                self.buffer.extend(self.unpadder.update(self.decryptor.update(chunk)))
            else:
                try:
                    self.buffer.extend(self.unpadder.update(self.decryptor.finalize()))
                    self.buffer.extend(self.unpadder.finalize())
                except ValueError as exc:
                    raise ValueError("MALFORMED_BACKUP") from exc
                self.finished = True
        amount = min(len(target), len(self.buffer))
        target[:amount] = self.buffer[:amount]
        del self.buffer[:amount]
        return amount


def _decrypt_ab_header(fields: list[str], password: str) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.padding import PKCS7

    try:
        user_salt, checksum_salt = bytes.fromhex(fields[0]), bytes.fromhex(fields[1])
        rounds = int(fields[2])
        iv, encrypted = bytes.fromhex(fields[3]), bytes.fromhex(fields[4])
        if not 1 <= rounds <= 1_000_000 or len(iv) != 16 or not encrypted or len(encrypted) % 16:
            raise ValueError("MALFORMED_BACKUP")
        derive = lambda value, salt: PBKDF2HMAC(algorithm=hashes.SHA1(), length=32,
                                                  salt=salt, iterations=rounds).derive(value)
        user_key = derive(password.encode("utf-8"), user_salt)
        decryptor = Cipher(algorithms.AES(user_key), modes.CBC(iv)).decryptor()
        unpadder = PKCS7(128).unpadder()
        decrypted = decryptor.update(encrypted) + decryptor.finalize()
        blob = unpadder.update(decrypted) + unpadder.finalize()
        position = 0

        def segment():
            nonlocal position
            if position >= len(blob):
                raise ValueError("MALFORMED_BACKUP")
            size = blob[position]
            position += 1
            if not size or position + size > len(blob):
                raise ValueError("MALFORMED_BACKUP")
            value = blob[position:position + size]
            position += size
            return value

        data_iv, data_key, stored_check = segment(), segment(), segment()
        if position != len(blob) or len(data_iv) != 16 or len(data_key) != 32 or len(stored_check) != 32:
            raise ValueError("MALFORMED_BACKUP")
        java_chars = "".join(chr(value if value < 128 else 0xFF00 + value) for value in data_key)
        if not secrets.compare_digest(derive(java_chars.encode("utf-8"), checksum_salt), stored_check):
            raise ValueError("LOCKED_BACKUP")
        return data_key, data_iv
    except ImportError as exc:
        raise ValueError("UNSUPPORTED_BACKUP_VARIANT: cryptography unavailable") from exc
    except ValueError as exc:
        if str(exc) in {"MALFORMED_BACKUP", "LOCKED_BACKUP"}:
            raise
        raise ValueError("LOCKED_BACKUP") from exc


def _tar_members(path: Path, *, ab: dict | None = None, password: str = ""):
    with path.open("rb") as source:
        if ab:
            source.seek(ab["payload_offset"])
            stream = source
            if ab["kind"] == "android_backup_encrypted":
                key, iv = _decrypt_ab_header(ab["encryption_fields"], password)
                stream = io.BufferedReader(_AesReader(stream, key, iv))
            if ab["compressed"]:
                stream = io.BufferedReader(_ZlibReader(stream))
            mode = "r|"
        else:
            stream = source
            mode = "r|*"
        with tarfile.open(fileobj=stream, mode=mode) as archive:
            for item in archive:
                yield item.name, item.size, item.isfile(), item.issym() or item.islnk()


def _seven_zip_members(path: Path, password: str = ""):
    name = ctypes.util.find_library("archive")
    if not name:
        raise RuntimeError("libarchive_missing")
    lib = ctypes.CDLL(name)
    lib.archive_read_new.restype = ctypes.c_void_p
    lib.archive_read_support_format_7zip.argtypes = [ctypes.c_void_p]
    lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
    lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.archive_read_add_passphrase.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
    lib.archive_entry_pathname.restype = ctypes.c_char_p
    lib.archive_entry_size.argtypes = [ctypes.c_void_p]
    lib.archive_entry_size.restype = ctypes.c_int64
    lib.archive_entry_filetype.argtypes = [ctypes.c_void_p]
    lib.archive_entry_filetype.restype = ctypes.c_uint
    lib.archive_read_data_skip.argtypes = [ctypes.c_void_p]
    lib.archive_read_free.argtypes = [ctypes.c_void_p]
    lib.archive_error_string.argtypes = [ctypes.c_void_p]
    lib.archive_error_string.restype = ctypes.c_char_p
    reader = lib.archive_read_new()
    if not reader:
        raise RuntimeError("archive_open_failed")
    try:
        lib.archive_read_support_format_7zip(reader)
        lib.archive_read_support_filter_all(reader)
        if password and lib.archive_read_add_passphrase(reader, password.encode("utf-8")) != 0:
            raise RuntimeError("UNSUPPORTED_ARCHIVE_VARIANT")
        if lib.archive_read_open_filename(reader, os.fsencode(path), 64 * 1024) != 0:
            raise RuntimeError((lib.archive_error_string(reader) or b"archive_open_failed").decode(errors="replace")[:120])
        entry = ctypes.c_void_p()
        while True:
            rc = lib.archive_read_next_header(reader, ctypes.byref(entry))
            if rc == 1:  # ARCHIVE_EOF
                break
            if rc != 0:
                raise RuntimeError((lib.archive_error_string(reader) or b"archive_read_failed").decode(errors="replace")[:120])
            value = lib.archive_entry_pathname(entry)
            if not value:
                raise RuntimeError("missing_member_path")
            path_value = value.decode("utf-8", errors="strict")
            size = lib.archive_entry_size(entry)
            kind = lib.archive_entry_filetype(entry)
            yield path_value, size, stat.S_ISREG(kind), stat.S_ISLNK(kind)
            if lib.archive_read_data_skip(reader) < 0:
                raise RuntimeError("archive_skip_failed")
    finally:
        lib.archive_read_free(reader)


def inspect(path: Path, kind: str, *, password: str = "") -> dict:
    start = time.monotonic()
    if kind in {"android_backup", "android_backup_encrypted"}:
        header = ab_header(path)
        if header["kind"] != kind:
            return {"inspected": False, "reason": header["kind"], "encryption_status": header.get("encryption_status")}
        if kind == "android_backup_encrypted" and not password:
            return {"inspected": False, "reason": "LOCKED_BACKUP", "encryption_status": "locked"}
        members = _tar_members(path, ab=header, password=password)
    elif kind == "tar_container":
        members = _tar_members(path)
    elif kind == "seven_zip_container":
        members = _seven_zip_members(path, password=password)
    else:
        return {"inspected": False, "reason": "unsupported_container_kind"}
    paths = []
    count = total = links = nested = 0
    try:
        for raw, size, regular, link in members:
            if time.monotonic() - start > MAX_SECONDS:
                return {"inspected": False, "reason": "inspection_time_limit", "entries": count}
            count += 1
            if count > MAX_ENTRIES or size > MAX_MEMBER_BYTES or size < 0:
                raise ValueError("RISK_REJECTED: archive_member_limit")
            _safe_path(raw)
            if link:
                links += 1
            if not regular:
                continue
            total += size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("RISK_REJECTED: total_expanded_size")
            paths.append(raw)
            if raw.lower().endswith(NESTED_SUFFIXES):
                nested += 1
        if total > path.stat().st_size * MAX_EXPANSION_RATIO and total > 16 * 1024 * 1024:
            raise ValueError("RISK_REJECTED: expansion_ratio")
        mapping = root_mapping(paths, android_backup=kind in {"android_backup", "android_backup_encrypted"})
        return {"inspected": True, "entries": count, "regular_files": len(paths),
                "skipped_links": links, "nested_container_detected": nested,
                "encryption_status": "unlocked" if kind == "android_backup_encrypted" else "none",
                "password_supplied": bool(password), **mapping}
    except (tarfile.TarError, zlib.error, RuntimeError, UnicodeError, OSError, ValueError) as exc:
        message = str(exc)[:120]
        locked = "passphrase" in message.lower() or "password" in message.lower() or "encrypted" in message.lower() or message == "LOCKED_BACKUP"
        return {"inspected": False, "reason": ("LOCKED_BACKUP" if kind == "android_backup_encrypted" else "LOCKED_ARCHIVE") if locked else message,
                "entries": count, "encryption_status": "locked" if locked else "unknown"}
    finally:
        close = getattr(members, "close", None)
        if close:
            close()
