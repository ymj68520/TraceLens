"""Deterministic, non-sensitive logical-container preflight fixtures."""

import ctypes
import ctypes.util
import io
import tarfile
import zlib
import time

import pytest

from httpserver.services import android_archive_preflight as archive
from httpserver.services import evidence_preflight as preflight


ANDROID_PATH = "data/data/com.android.providers.telephony/databases/mmssms.db"


def _tar_bytes(path=ANDROID_PATH):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as writer:
        value = b"SQLite format 3\0" + b"\0" * 128
        info = tarfile.TarInfo(path)
        info.size = len(value)
        writer.addfile(info, io.BytesIO(value))
    return result.getvalue()


def _seven_zip(path, entries):
    library = ctypes.util.find_library("archive")
    if not library:
        pytest.skip("libarchive unavailable")
    lib = ctypes.CDLL(library)
    lib.archive_write_new.restype = ctypes.c_void_p
    lib.archive_write_set_format_7zip.argtypes = [ctypes.c_void_p]
    lib.archive_write_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.archive_entry_new.restype = ctypes.c_void_p
    lib.archive_entry_set_pathname.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.archive_entry_set_filetype.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    lib.archive_entry_set_perm.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.archive_entry_set_size.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    lib.archive_write_header.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.archive_write_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.archive_write_data.restype = ctypes.c_ssize_t
    lib.archive_entry_free.argtypes = [ctypes.c_void_p]
    lib.archive_write_close.argtypes = [ctypes.c_void_p]
    lib.archive_write_free.argtypes = [ctypes.c_void_p]
    writer = lib.archive_write_new()
    try:
        assert lib.archive_write_set_format_7zip(writer) == 0
        assert lib.archive_write_open_filename(writer, str(path).encode()) == 0
        for member, data in entries.items():
            item = lib.archive_entry_new()
            try:
                lib.archive_entry_set_pathname(item, member.encode())
                lib.archive_entry_set_filetype(item, 0o100000)
                lib.archive_entry_set_perm(item, 0o600)
                lib.archive_entry_set_size(item, len(data))
                assert lib.archive_write_header(writer, item) == 0
                value = ctypes.create_string_buffer(data)
                assert lib.archive_write_data(writer, value, len(data)) == len(data)
            finally:
                lib.archive_entry_free(item)
        assert lib.archive_write_close(writer) == 0
    finally:
        lib.archive_write_free(writer)


def _encrypted_ab_bytes(tar_bytes: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.padding import PKCS7

    user_salt = bytes(range(1, 65))
    check_salt = bytes(range(100, 164))
    user_iv = bytes(range(16))
    data_iv = bytes(range(20, 36))
    data_key = bytes(range(150, 182))
    rounds = 10000

    def derive(value, salt):
        return PBKDF2HMAC(algorithm=hashes.SHA1(), length=32,
                         salt=salt, iterations=rounds).derive(value)

    def encrypt(data, key, iv):
        pad = PKCS7(128).padder()
        value = pad.update(data) + pad.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return cipher.update(value) + cipher.finalize()

    user_key = derive(password.encode(), user_salt)
    java_chars = "".join(chr(value if value < 128 else 0xFF00 + value) for value in data_key)
    checksum = derive(java_chars.encode(), check_salt)
    blob = bytes([16]) + data_iv + bytes([32]) + data_key + bytes([32]) + checksum
    header = b"ANDROID BACKUP\n5\n1\nAES-256\n" + b"\n".join([
        user_salt.hex().encode(), check_salt.hex().encode(), str(rounds).encode(),
        user_iv.hex().encode(), encrypt(blob, user_key, user_iv).hex().encode(),
    ]) + b"\n"
    return header + encrypt(zlib.compress(tar_bytes), data_key, data_iv)


@pytest.mark.parametrize("suffix,compression", [
    (".tar", None), (".tar.gz", "gz"), (".tgz", "gz"), (".tar.xz", "xz"),
])
def test_tar_variants_normalize(tmp_path, suffix, compression):
    path = tmp_path / ("android" + suffix)
    with tarfile.open(path, "w:" + compression if compression else "w") as writer:
        data = b"SQLite format 3\0" + b"\0" * 128
        item = tarfile.TarInfo("phone_export/" + ANDROID_PATH)
        item.size = len(data)
        writer.addfile(item, io.BytesIO(data))
    assert preflight._probe(path)["kind"] == "tar_container"
    result = archive.inspect(path, "tar_container")
    assert result["inspected"] is True
    assert result["ready"] is True
    assert result["root_mapping"] == "phone_export/"
    assert result["regular_files"] == 1


def test_7z_enumerates_and_normalizes(tmp_path):
    path = tmp_path / "android.7z"
    _seven_zip(path, {ANDROID_PATH: b"SQLite format 3\0" + b"x" * 120})
    assert preflight._probe(path)["kind"] == "seven_zip_container"
    result = archive.inspect(path, "seven_zip_container")
    assert result["inspected"] is True
    assert result["ready"] is True
    assert result["regular_files"] == 1


def test_ab_magic_and_compressed_stream(tmp_path):
    path = tmp_path / "android.ab"
    path.write_bytes(b"ANDROID BACKUP\n5\n1\nnone\n" + zlib.compress(_tar_bytes()))
    assert preflight._probe(path)["kind"] == "android_backup"
    result = archive.inspect(path, "android_backup")
    assert result["inspected"] is True
    assert result["ready"] is True
    assert result["regular_files"] == 1


def test_ab_encrypted_unsupported_and_malformed(tmp_path):
    path = tmp_path / "android.ab"
    path.write_bytes(_encrypted_ab_bytes(_tar_bytes(), "test-password"))
    assert preflight._probe(path)["kind"] == "android_backup_encrypted"
    locked = archive.inspect(path, "android_backup_encrypted")
    assert locked["reason"] == "LOCKED_BACKUP"
    wrong = archive.inspect(path, "android_backup_encrypted", password="wrong")
    assert wrong["reason"] == "LOCKED_BACKUP"
    unlocked = archive.inspect(path, "android_backup_encrypted", password="test-password")
    assert unlocked["inspected"] and unlocked["ready"]
    assert unlocked["encryption_status"] == "unlocked"
    path.write_bytes(b"ANDROID BACKUP\n99\n1\nnone\n")
    assert preflight._probe(path)["kind"] == "android_backup_unsupported"
    path.write_bytes(b"random bytes")
    assert preflight._probe(path)["kind"] == "unknown_file"


def test_encrypted_ab_preflight_never_persists_password(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "backup.ab"
    path.write_bytes(_encrypted_ab_bytes(_tar_bytes(), "test-password"))
    monkeypatch.setattr(preflight, "evidence_inbox", lambda: inbox.resolve())
    monkeypatch.setattr(preflight, "job_root", lambda: tmp_path / "jobs")
    candidate_id = preflight.list_candidates()[0]["id"]
    job_id = preflight.start_job(candidate_id, full_hash=True, password="test-password")["id"]
    for _ in range(100):
        job = preflight.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert job["status"] == "completed"
    assert job["detected"]["adapter"] == "android-backup"
    assert job["archive"]["ready"] is True
    assert job["password_supplied"] is True
    assert "test-password" not in (tmp_path / "jobs" / job_id / "job.json").read_text()


def test_traversal_is_risk_rejected(tmp_path):
    path = tmp_path / "unsafe.tar"
    path.write_bytes(_tar_bytes("../../etc/passwd"))
    assert archive.inspect(path, "tar_container")["reason"].startswith("RISK_REJECTED")


def test_no_android_root_is_not_ready(tmp_path):
    path = tmp_path / "notes.tar"
    path.write_bytes(_tar_bytes("notes/data.txt"))
    result = archive.inspect(path, "tar_container")
    assert result["inspected"] is True
    assert result["ready"] is False
