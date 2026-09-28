"""Synthetic Android tree -> dir/ZIP/TAR/7z/AB -> real AndroidAnalyzer rows.

No case data or vendor binaries. The 7z fixture uses libarchive's open-source
writer C API through ctypes; the production extractor uses its reader C API.
"""

import argparse
import ctypes
import ctypes.util
import io
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import zipfile
import zlib
from collections import Counter
from pathlib import Path


SMS = "data/data/com.android.providers.telephony/databases/mmssms.db"
CONTACTS = "data/data/com.android.providers.contacts/databases/contacts2.db"
PACKAGES = "data/system/packages.xml"
WIFI = "data/misc/wifi/WifiConfigStore.xml"
EXPECTED = {"sms_messages": 2, "contacts": 1, "installed_packages": 1, "wifi_networks": 1}
# Independent literals, not generated from the parser's output. Counter keeps
# legitimate duplicates instead of silently converting to a set.
EXPECTED_CONTENT = {
    "sms_messages": Counter({("10086", "fixture-message-1", 1700000000000, 1): 1,
                             ("10010", "fixture-message-2", 1700000001000, 2): 1}),
    "contacts": Counter({("Fixture Contact", "12345"): 1}),
    "installed_packages": Counter({("com.fixture.app", "1"): 1}),
    "wifi_networks": Counter({("FixtureWifi", ""): 1}),
}


def assert_artifact_content(db_path: Path):
    queries = {
        "sms_messages": "SELECT address,body,date,type FROM sms_messages",
        "contacts": "SELECT display_name,phone_number FROM contacts",
        "installed_packages": "SELECT package_name,version FROM installed_packages",
        "wifi_networks": "SELECT ssid,key_mgmt FROM wifi_networks",
    }
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        for table, query in queries.items():
            actual = Counter(con.execute(query).fetchall())
            assert actual == EXPECTED_CONTENT[table], (db_path, table, actual, EXPECTED_CONTENT[table])


def build_tree(root: Path):
    sms_path = root / SMS
    sms_path.parent.mkdir(parents=True, exist_ok=True)
    sms = sqlite3.connect(sms_path)
    sms.execute("PRAGMA journal_mode=WAL")
    sms.execute("CREATE TABLE sms(address TEXT, body TEXT, date INTEGER, type INTEGER)")
    sms.execute("INSERT INTO sms VALUES ('10086','fixture-message-1',1700000000000,1)")
    sms.commit()
    sms.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sms.execute("INSERT INTO sms VALUES ('10010','fixture-message-2',1700000001000,2)")
    sms.commit()
    contacts_path = root / CONTACTS
    contacts_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(contacts_path) as con:
        con.execute("CREATE TABLE people(display_name TEXT,data1 TEXT,mimetype TEXT)")
        con.execute("INSERT INTO people VALUES ('Fixture Contact','12345','vnd.android.cursor.item/phone_v2')")
        con.execute("CREATE VIEW view_contacts AS SELECT * FROM people")
    package_path = root / PACKAGES
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_text('<packages>\n<package name="com.fixture.app" codePath="/data/app/com.fixture.app" version="1" installer="test"/>\n</packages>', encoding="utf-8")
    wifi_path = root / WIFI
    wifi_path.parent.mkdir(parents=True, exist_ok=True)
    wifi_path.write_text('<String name="SSID">&quot;FixtureWifi&quot;</String>\n<String name="PreSharedKey">&quot;fixture-pass&quot;</String>\n', encoding="utf-8")
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert SMS + "-wal" in files
    sms.close()
    return files


def write_7z(path: Path, files: dict[str, bytes]):
    lib = ctypes.CDLL(ctypes.util.find_library("archive"))
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
        assert lib.archive_write_open_filename(writer, os.fsencode(path)) == 0
        for name, data in sorted(files.items()):
            entry = lib.archive_entry_new()
            try:
                lib.archive_entry_set_pathname(entry, name.encode())
                lib.archive_entry_set_filetype(entry, 0o100000)
                lib.archive_entry_set_perm(entry, 0o600)
                lib.archive_entry_set_size(entry, len(data))
                assert lib.archive_write_header(writer, entry) == 0
                content = ctypes.create_string_buffer(data)
                assert lib.archive_write_data(writer, content, len(data)) == len(data)
            finally:
                lib.archive_entry_free(entry)
        assert lib.archive_write_close(writer) == 0
    finally:
        lib.archive_write_free(writer)


def encrypted_ab_bytes(tar_bytes: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.padding import PKCS7

    user_salt = bytes(range(1, 65))
    checksum_salt = bytes(range(100, 164))
    user_iv = bytes(range(16))
    data_iv = bytes(range(20, 36))
    data_key = bytes(range(150, 182))

    def derive(value, salt):
        return PBKDF2HMAC(algorithm=hashes.SHA1(), length=32,
                         salt=salt, iterations=10000).derive(value)

    def encrypt(value, key, iv):
        padding = PKCS7(128).padder()
        padded = padding.update(value) + padding.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return cipher.update(padded) + cipher.finalize()

    user_key = derive(password.encode(), user_salt)
    java_chars = "".join(chr(value if value < 128 else 0xFF00 + value) for value in data_key)
    check = derive(java_chars.encode(), checksum_salt)
    blob = bytes([16]) + data_iv + bytes([32]) + data_key + bytes([32]) + check
    return (b"ANDROID BACKUP\n5\n1\nAES-256\n" + b"\n".join([
        user_salt.hex().encode(), checksum_salt.hex().encode(), b"10000",
        user_iv.hex().encode(), encrypt(blob, user_key, user_iv).hex().encode(),
    ]) + b"\n" + encrypt(zlib.compress(tar_bytes), data_key, data_iv))


def package_sources(root: Path, files: dict[str, bytes]):
    zip_path = root / "android.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as writer:
        for name, data in sorted(files.items()):
            writer.writestr(name, data)
    tar_path = root / "android.tar"
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as writer:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            writer.addfile(info, io.BytesIO(data))
    tar_path.write_bytes(tar_bytes.getvalue())
    seven_path = root / "android.7z"
    write_7z(seven_path, files)
    ab_path = root / "android.ab"
    ab_path.write_bytes(b"ANDROID BACKUP\n5\n1\nnone\n" + zlib.compress(tar_bytes.getvalue()))
    return {"dir": root / "logical", "zip": zip_path, "tar": tar_path,
            "seven-zip": seven_path, "android-backup": ab_path}


def counts(db_path: Path):
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        return {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in EXPECTED}


def run(analyzer: Path):
    with tempfile.TemporaryDirectory(prefix="tracelens_archive_e2e_") as directory:
        root = Path(directory)
        logical = root / "logical"
        logical.mkdir()
        files = build_tree(logical)
        sources = package_sources(root, files)
        observed = {}
        for mode, source in sources.items():
            output_dir = root / ("out_" + mode)
            output_dir.mkdir()
            command = [str(analyzer), str(source), "--android-analyze",
                       "--android-source", mode, "--no-ai", "--db-dir", str(output_dir)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if completed.returncode:
                raise AssertionError(f"{mode} analyzer failed ({completed.returncode}): {completed.stderr[-1000:]}")
            db = output_dir / (source.stem + "_files.db")
            assert db.is_file(), f"{mode} did not produce Android artifact DB"
            observed[mode] = counts(db)
            if observed[mode] != EXPECTED:
                with sqlite3.connect(db) as con:
                    coverage = con.execute("SELECT artifact_kind,source_path,status FROM android_source_coverage WHERE source_path LIKE '%packages.xml%'").fetchall()
                    all_coverage = con.execute("SELECT artifact_kind,source_path,status FROM android_source_coverage LIMIT 12").fetchall()
                raise AssertionError(f"{mode} artifact mismatch: {observed[mode]}; coverage={coverage}; "
                                     f"all_coverage={all_coverage}; "
                                     f"package_log={[line for line in completed.stdout.splitlines() if 'packag' in line.lower()][-12:]}; "
                                     f"stderr={completed.stderr[-1000:]}")
            assert_artifact_content(db)
            if mode in {"tar", "seven-zip", "android-backup"}:
                with sqlite3.connect(db) as con:
                    provenance = con.execute("SELECT normalized_android_path, source_member_path, member_sha256 "
                                             "FROM android_source_provenance").fetchall()
                    assert any(row[0] == SMS and len(row[2]) == 64 for row in provenance), mode
                    assert any(row[0] == WIFI for row in provenance), mode
                    coverage = dict(con.execute(
                        "SELECT normalized_path,status FROM android_container_coverage").fetchall())
                    assert coverage[SMS] == "PARSED", mode
                    assert coverage[CONTACTS] == "PARSED", mode
                    assert coverage[PACKAGES] == "PARSED", mode
                    assert coverage[WIFI] == "PARSED", mode
        assert len({tuple(value.items()) for value in observed.values()}) == 1
        encrypted = root / "encrypted.ab"
        encrypted.write_bytes(encrypted_ab_bytes(sources["tar"].read_bytes(), "fixture-secret"))
        encrypted_out = root / "out_encrypted"
        encrypted_out.mkdir()
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"fixture-secret\n")
        finally:
            os.close(write_fd)
        try:
            command = [str(analyzer), str(encrypted), "--android-analyze",
                       "--android-source", "android-backup", "--backup-password-fd", str(read_fd),
                       "--no-ai", "--db-dir", str(encrypted_out)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120,
                                       pass_fds=(read_fd,))
        finally:
            os.close(read_fd)
        assert completed.returncode == 0, completed.stderr[-1000:]
        assert counts(encrypted_out / "encrypted_files.db") == EXPECTED
        print({"artifact_counts": EXPECTED, "modes": list(observed), "differential_equal": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    args = parser.parse_args()
    run(args.analyzer.resolve(strict=True))
