"""Bounded, read-only triage for unknown forensic data sources.

The result is a format hypothesis and an integrity/inventory record, never a
claim that acquisition or artifact parsing succeeded. Nothing is extracted or
executed from the selected evidence. Large hashes run in a background thread.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import re
import stat
import threading
import time
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import android_archive_preflight, android_image_preflight, android_container_pipeline
from . import aliyun_image
from .android_sparse_image import validate_sparse

from ..config import get_data_root, get_project_root

_ID = re.compile(r"[0-9a-f]{24}\Z")
_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH_CHUNK = 4 * 1024 * 1024
_QUICK_ENTRY_LIMIT = 20_000
_QUICK_SECONDS = 15
_FULL_ENTRY_LIMIT = 1_000_000
_ZIP_INSPECTION_LIMIT = 16 * 1024 * 1024
_ZIP_ENTRY_LIMIT = 20_000
_active: dict[str, threading.Event] = {}
_lock = threading.Lock()


class PreflightError(ValueError):
    pass


class _Cancelled(Exception):
    pass


def evidence_inbox() -> Path:
    configured = os.environ.get("TRACELENS_EVIDENCE_INBOX")
    return Path(configured).expanduser().resolve() if configured else get_project_root().parent.resolve()


def job_root() -> Path:
    return get_data_root() / "evidence_preflight"


def _candidate_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:24]



_THUNDERFORENSIC_SCAN_MEMBER_LIMIT = 2_000_000
_THUNDERFORENSIC_MANIFEST = "ThunderForensic.json"
_THUNDERFORENSIC_PHONE_DATA = "PhoneData/"


def _pax_fields(payload: bytes) -> tuple[str, int | None]:
    """Return (path, size) from a POSIX PAX extended header."""
    path = ""
    size = None
    position = 0
    while position < len(payload):
        space = payload.find(b" ", position)
        if space <= position:
            break
        try:
            length = int(payload[position:space])
        except ValueError:
            break
        if length <= 0 or position + length > len(payload):
            break
        record = payload[position:position + length]
        if record.endswith(b"\n"):
            record = record[:-1]
        record_space = record.find(b" ")
        if record_space != -1:
            key, _, value = record[record_space + 1:].partition(b"=")
            if key == b"path":
                path = value.decode("utf-8", "replace")
            elif key == b"size":
                try:
                    size = int(value)
                except ValueError:
                    size = None
        position += length
    return path, size


def _is_thunderforensic_tar(path: Path) -> bool:
    """Bounded ustar header walk looking for the ThunderForensic markers.

    The writer emits a non-octal gid ("-6667000") on some members and, for
    vivo, on the very first member. libarchive and Python's tarfile reject or
    slowly iterate such containers, so the header walk is done directly over a
    read-only mapping. Data blocks are skipped by offset; GNU long names and
    PAX path/size records are resolved. The manifest can sit at the very end
    (vivo), so the walk continues until both markers are seen or the member
    cap is reached.
    """
    try:
        with path.open("rb") as source:
            file_size = os.fstat(source.fileno()).st_size
            if file_size < 1024:
                return False
            try:
                mapped = mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                mapped = None

            def read_at(offset: int, length: int) -> bytes:
                if mapped is not None:
                    return mapped[offset:offset + length]
                return os.pread(source.fileno(), length, offset)

            saw_manifest = saw_phone_data = False
            offset = 0
            scanned = 0
            long_name = ""
            pax_path = ""
            pax_size = None
            try:
                while offset + 512 <= file_size:
                    block = read_at(offset, 512)
                    if len(block) < 512 or block == b"\0" * 512:
                        break
                    if block[257:262] != b"ustar":
                        return False
                    raw_size = block[124:136].rstrip(b"\0 ")
                    try:
                        size = int(raw_size, 8) if raw_size else 0
                    except ValueError:
                        return False
                    data_offset = offset + 512
                    if data_offset + size > file_size:
                        return False
                    typeflag = block[156:157]
                    effective = size
                    if typeflag == b"L":
                        raw = read_at(data_offset, min(size, 1 << 20))
                        long_name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
                    elif typeflag == b"x":
                        raw = read_at(data_offset, min(size, 4 << 20))
                        pax_path, pax_size = _pax_fields(raw)
                    elif typeflag in (b"g", b"K"):
                        pass
                    else:
                        name = pax_path or long_name or block[:100].split(b"\0", 1)[0].decode(
                            "utf-8", "replace")
                        if pax_size is not None:
                            effective = pax_size
                            if data_offset + effective > file_size:
                                return False
                        if typeflag in (b"0", b"\0", b"7"):
                            if name == _THUNDERFORENSIC_MANIFEST:
                                saw_manifest = True
                            if name.startswith(_THUNDERFORENSIC_PHONE_DATA):
                                saw_phone_data = True
                        long_name = ""
                        pax_path = ""
                        pax_size = None
                    offset = data_offset + ((effective + 511) // 512) * 512
                    scanned += 1
                    if scanned > _THUNDERFORENSIC_SCAN_MEMBER_LIMIT:
                        return False
                    if saw_manifest and saw_phone_data:
                        return True
            finally:
                if mapped is not None:
                    mapped.close()
    except (OSError, ValueError):
        return False
    return False


def _is_meiya_container(path: Path) -> bool:
    """True when `path` looks like a Meiya (MobileMaster FL-901) container.

    Meiya stores standard SQLite databases XOR-obfuscated with a fixed
    1024-byte mask, so the file length is a multiple of the page size and the
    header is neither plaintext SQLite nor a constant run. Only the header is
    read here; the mask itself is derived and verified during analysis.
    """
    try:
        stat_result = path.lstat()
        if not stat.S_ISREG(stat_result.st_mode) or stat_result.st_size <= 0:
            return False
        if stat_result.st_size % 1024 != 0:
            return False
        with path.open("rb") as source:
            head = source.read(16)
    except OSError:
        return False
    if len(head) < 16:
        return False
    if head.startswith(b"SQLite format 3\x00"):
        return False
    return len(set(head)) > 1


def _probe_meiya_case(path: Path) -> dict | None:
    """Detect a Meiya case export directory or a single .mf case file."""
    try:
        if path.is_dir():
            case_files = [item for item in sorted(path.iterdir())
                          if item.is_file() and item.suffix.lower() == ".mf"
                          and _is_meiya_container(item)]
            if case_files:
                return {"kind": "meiya_case_export", "adapter": "meiya",
                        "confidence": "high", "container": case_files[0].name,
                        "reason": "美亚柏科（MobileMaster FL-901）案件导出：容器为 1024 字节周期 XOR 混淆的 SQLite，掩码在分析阶段自推导"}
            # The selected directory may itself be one device folder.
            self_dmf = path / f"{path.name}.dmf"
            if self_dmf.is_file() and _is_meiya_container(self_dmf):
                return {"kind": "meiya_case_export", "adapter": "meiya",
                        "confidence": "medium", "container": self_dmf.name,
                        "reason": "美亚柏科（MobileMaster FL-901）单个设备目录：仅含该设备的规范化库，案件级容器需选择上级案件目录"}
            device_containers = []
            for child in sorted(path.iterdir()):
                if not child.is_dir():
                    continue
                candidate = child / f"{child.name}.dmf"
                if candidate.is_file() and _is_meiya_container(candidate):
                    device_containers.append(candidate)
            if device_containers:
                return {"kind": "meiya_case_export", "adapter": "meiya",
                        "confidence": "high",
                        "container": device_containers[0].parent.name,
                        "reason": "美亚柏科（MobileMaster FL-901）设备目录：含 <设备>.dmf 规范化库"}
            return None
        if path.suffix.lower() == ".mf" and _is_meiya_container(path):
            return {"kind": "meiya_case_export", "adapter": "meiya",
                    "confidence": "medium", "container": path.name,
                    "reason": "美亚案件库 .mf 文件；建议选择整个案件目录以同时解析设备库"}
    except OSError:
        return None
    return None


def _probe(path: Path) -> dict:
    if path.is_dir():
        meiya = _probe_meiya_case(path)
        if meiya is not None:
            return meiya
        header = path / ".info.json"
        if header.is_file() and not header.is_symlink() and header.stat().st_size <= 8 * 1024 * 1024 and (path / "files").is_dir():
            try:
                metadata = json.loads(header.read_text(encoding="utf-8-sig"))
                if isinstance(metadata.get("BackupFileHeaderInfo"), dict) and isinstance(metadata.get("BackupFileModuleInfo"), list):
                    return {"kind": "harmony_decrypted_backup", "adapter": "harmony-backup", "confidence": "high",
                            "reason": "Backup structure recognized; decrypted members and coverage are verified during analysis"}
            except (OSError, UnicodeError, ValueError, AttributeError):
                pass
        if (path / "index.html").is_file() and any((path / "report").glob("*/export.db")):
            return {"kind": "derived_html_report", "adapter": "android_report", "confidence": "high"}
        if (path / "descript.xml").is_file() and any(path.glob("*.bak")):
            return {"kind": "miui_backup", "adapter": "miui-backup", "confidence": "high"}
        thunder_tars = []
        for tar_dir in (path / "filesystem" / "1" / "tar", path):
            if not tar_dir.is_dir():
                continue
            try:
                thunder_tars = [item for item in sorted(tar_dir.iterdir())
                                if item.suffix.lower() == ".tar"
                                and _is_thunderforensic_tar(item)]
            except OSError:
                thunder_tars = []
            if thunder_tars:
                break
        if thunder_tars:
            return {"kind": "thunderforensic_backup", "adapter": "thunder-backup",
                    "confidence": "high",
                    "container": thunder_tars[0].name,
                    "reason": "ThunderForensic（雷电手机快取）提取工程目录（OPPO/vivo/OnePlus 等）；适配器在分析阶段解析容器成员"}

        if any((path / marker).exists() for marker in ("data/data", "data/user/0", "system/build.prop")):
            return {"kind": "android_logical_tree", "adapter": "dir", "confidence": "medium"}
        return {"kind": "unknown_directory", "adapter": None, "confidence": "low"}

    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise PreflightError("source is not a regular file")
        header = source.read(4096)
    suffix = path.suffix.lower()
    if header.startswith(b"ANDROID BACKUP\n"):
        info = android_archive_preflight.ab_header(path)
        return {"kind": info["kind"], "adapter": None, "confidence": "high",
                "encryption_status": info.get("encryption_status", "unknown"),
                "backup_version": info.get("version"), "reason": info.get("reason")}
    if header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
        return {"kind": "zip_container", "adapter": None, "confidence": "high"}
    if header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return {"kind": "seven_zip_container", "adapter": None, "confidence": "high"}
    if header.startswith(b"SQLite format 3\x00"):
        sidecars = [suffix for suffix in ("-wal", "-shm", "-journal")
                    if path.with_name(path.name + suffix).is_file()]
        return {"kind": "sqlite_database", "adapter": "sqlite_inventory",
                "confidence": "high", "sidecars_present": sidecars}
    if header.startswith(b"\x3a\xff\x26\xed"):
        return {"kind": "android_sparse_image", "adapter": None, "confidence": "high"}
    if header[1024:1028] == b"\x10\x20\xf5\xf2" or header[1080:1082] == b"\x53\xef":
        return {"kind": "raw_image_candidate", "adapter": None,
                "confidence": "filesystem_magic_candidate"}
    if header.startswith(b"EVF\x09\x0d\x0a\xff\x00"):
        return {"kind": "ewf_candidate", "adapter": None,
                "confidence": "ewf_header_candidate"}
    if header[257:262] == b"ustar":
        thunder = _is_thunderforensic_tar(path)
        if thunder:
            return {"kind": "thunderforensic_backup", "adapter": "thunder-backup",
                    "confidence": "high",
                    "reason": "ThunderForensic（雷电手机快取）提取容器（OPPO/vivo/OnePlus 等）；适配器在分析阶段解析 PhoneData 成员"}
        return {"kind": "tar_container", "adapter": None, "confidence": "high"}
    if (header.startswith(b"\x1f\x8b") and path.name.lower().endswith((".tar.gz", ".tgz"))) or (
        header.startswith(b"\xfd7zXZ\x00") and path.name.lower().endswith(".tar.xz")
    ):
        if header.startswith(b"\x1f\x8b"):
            cloud = aliyun_image.inspect_header(path)
            if cloud.get("candidate"):
                return {"kind": "aliyun_raw_export", "adapter": "aliyun-image", "confidence": "high",
                        "reason": "RAW 系统盘导出包候选；解包时继续校验完整容器和来源"}
        return {"kind": "tar_container", "adapter": None, "confidence": "medium"}
    meiya = _probe_meiya_case(path)
    if meiya is not None:
        return meiya
    if suffix in {".mfc", ".m01", ".mf", ".bcp"}:
        return {"kind": "vendor_container_unknown", "adapter": None, "confidence": "extension_only"}
    if suffix in {".e01", ".e02"}:
        return {"kind": "ewf_candidate", "adapter": None, "confidence": "extension_only"}
    if suffix in {".dd", ".img", ".raw", ".bin"}:
        return {"kind": "raw_image_candidate", "adapter": None, "confidence": "extension_only"}
    return {"kind": "unknown_file", "adapter": None, "confidence": "low"}


def list_candidates() -> list[dict]:
    base = evidence_inbox()
    if not base.is_dir():
        return []
    results = []
    for entry in sorted(base.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            continue
        resolved = entry.resolve()
        if resolved == get_project_root().resolve() or not resolved.is_relative_to(base):
            continue
        try:
            info = _probe(resolved)
            size = resolved.stat().st_size if resolved.is_file() else None
        except (OSError, ValueError):
            continue
        results.append({"id": _candidate_id(resolved), "name": entry.name, "size": size, **info})
        if len(results) >= 200:
            break
    return results


def _selected(candidate_id: str) -> Path:
    if not isinstance(candidate_id, str) or not _ID.fullmatch(candidate_id):
        raise PreflightError("invalid evidence selection")
    for item in list_candidates():
        if item["id"] == candidate_id:
            selected = evidence_inbox() / item["name"]
            if selected.is_symlink():
                break
            path = selected.resolve(strict=True)
            if not path.is_relative_to(evidence_inbox()):
                break
            return path
    raise PreflightError("selected evidence is no longer available")


def _job_dir(job_id: str) -> Path:
    if not _JOB_ID.fullmatch(job_id or ""):
        raise PreflightError("invalid preflight job ID")
    return job_root() / job_id


def _write_job(job_id: str, result: dict) -> None:
    directory = _job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = directory / "job.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.replace(tmp, directory / "job.json")


def get_job(job_id: str) -> dict:
    path = _job_dir(job_id) / "job.json"
    if not path.is_file():
        raise FileNotFoundError("preflight job not found")
    result = json.loads(path.read_text(encoding="utf-8"))
    with _lock:
        active = job_id in _active
    if result["status"] in {"queued", "running"} and not active:
        result = {**result, "status": "interrupted", "warning": "service restarted; full hash not verified"}
    return result


def _zip_summary(path: Path) -> dict:
    if path.stat().st_size > _ZIP_INSPECTION_LIMIT:
        return {"inspected": False, "reason": "large archive: metadata listing deferred to isolated inspection"}
    counts = Counter()
    warnings = set()
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _ZIP_ENTRY_LIMIT:
                return {"inspected": False, "reason": "archive has too many entries"}
            for info in entries:
                name = info.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if name.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", name) or ".." in parts:
                    warnings.add("archive_path_escape")
                if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                    warnings.add("archive_symlink")
                if info.flag_bits & 1:
                    warnings.add("encrypted_entries")
                if info.compress_size and info.file_size > max(info.compress_size, 1) * 1000:
                    warnings.add("extreme_compression_ratio")
                if name.startswith(("data/data/", "data/user/0/")):
                    counts["android_logical_files"] += 1
                if name.endswith((".db", ".sqlite")):
                    counts["database_files"] += 1
                counts["entries"] += 1
    except (zipfile.BadZipFile, OSError):
        return {"inspected": False, "reason": "invalid ZIP structure"}
    return {"inspected": True, "counts": dict(counts), "warnings": sorted(warnings)}


def _hash_file(path: Path, cancelled: threading.Event, on_progress) -> tuple[str, int]:
    digest = hashlib.sha256()
    processed = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise PreflightError("source is not a regular file")
        while block := source.read(_HASH_CHUNK):
            if cancelled.is_set():
                raise _Cancelled()
            digest.update(block)
            processed += len(block)
            on_progress(len(block))
        opened_after = os.fstat(source.fileno())
    after = path.stat(follow_symlinks=False)
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if before_id != (opened_after.st_dev, opened_after.st_ino, opened_after.st_size, opened_after.st_mtime_ns) or before_id != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise PreflightError("source changed during hashing")
    return digest.hexdigest(), processed


def _run_job(job_id: str, path: Path, full_hash: bool, cancelled: threading.Event,
             password: bytearray | None = None, selected_slot: int = 0) -> None:
    result = get_job(job_id)
    last_write = time.monotonic()

    def advance(amount: int) -> None:
        nonlocal last_write
        result["bytes_read"] += amount
        if time.monotonic() - last_write >= 1:
            _write_job(job_id, result)
            last_write = time.monotonic()

    try:
        result["status"] = "running"
        result["started_at"] = datetime.now(timezone.utc).isoformat()
        result["detected"] = _probe(path)
        _write_job(job_id, result)
        if path.is_file():
            result["file_count"] = 1
            result["source_size"] = path.stat().st_size
            if full_hash:
                result["sha256"], _ = _hash_file(path, cancelled, advance)
            if result["detected"]["kind"] == "aliyun_raw_export":
                result["aliyun_image"] = aliyun_image.inspect_header(path)
                if not result["aliyun_image"].get("ready"):
                    raise PreflightError("阿里云镜像导出包头部校验失败")
            if result["detected"]["kind"] == "zip_container":
                result["archive"] = _zip_summary(path)
                severe = {"archive_path_escape", "archive_symlink", "extreme_compression_ratio"}
                if severe.intersection(result["archive"].get("warnings", [])):
                    result["detected"] = {"kind": "zip_container_unsafe", "adapter": None, "confidence": "high"}
                elif result["archive"].get("counts", {}).get("android_logical_files"):
                    result["detected"] = {"kind": "android_logical_zip", "adapter": "zip", "confidence": "high"}
            if result["detected"]["kind"] in {"tar_container", "seven_zip_container", "android_backup", "android_backup_encrypted"}:
                kind = result["detected"]["kind"]
                result["archive"] = android_archive_preflight.inspect(
                    path, kind, password=password.decode("utf-8") if password else "")
                if result["archive"].get("inspected") and result["archive"].get("ready"):
                    result["detected"]["adapter"] = {
                        "tar_container": "tar", "seven_zip_container": "seven-zip",
                        "android_backup": "android-backup",
                        "android_backup_encrypted": "android-backup",
                    }[kind]
                    result["detected"]["analysis_state"] = "CAN_NORMALIZE"
                    result["detected"]["root_mapping"] = result["archive"]["root_mapping"]
                elif str(result["archive"].get("reason", "")).startswith("RISK_REJECTED"):
                    result["detected"]["risk_status"] = "RISK_REJECTED"
            if result["detected"]["kind"] in {"raw_image_candidate", "ewf_candidate", "android_sparse_image"}:
                original_kind = result["detected"]["kind"]
                if original_kind == "android_sparse_image" and not full_hash:
                    result["container"] = {"kind": "ANDROID_SPARSE_UNREADY", "ready": False,
                                            "sparse": validate_sparse(path), "reason": "FULL_HASH_REQUIRED"}
                elif full_hash:
                    preview = _job_dir(job_id) / "work"
                    preview.mkdir(mode=0o700, exist_ok=True)
                    try:
                        result["container"] = android_container_pipeline.AndroidImageNormalizationPipeline.inspect(
                            path, preview, source_sha256=result["sha256"], full_hash=True,
                            selected_slot=selected_slot)
                    except Exception as exc:
                        result["container"] = {"kind": "CONTAINER_INSPECTION_FAILED", "ready": False,
                                               "reason": str(exc).split(":", 1)[0][:100]}
                container = result.get("container") or {}
                kinds = {"ANDROID_SPARSE_USERDATA": "android_sparse_userdata",
                         "ANDROID_RAW_SUPER": "android_raw_super",
                         "ANDROID_SPARSE_SUPER": "android_sparse_super",
                         "ANDROID_FULL_DISK_SUPER": "android_full_disk_super"}
                if container.get("ready") and container.get("kind") in kinds:
                    result["detected"] = {"kind": kinds[container["kind"]],
                        "adapter": "android-container", "confidence": "high",
                        "analysis_state": "CAN_NORMALIZE" if container["kind"] == "ANDROID_SPARSE_USERDATA"
                            else "CAN_NORMALIZE_READY"}
                elif original_kind in {"raw_image_candidate", "ewf_candidate"} and \
                        container.get("kind") in (None, "NOT_CONTAINER"):
                    result["image"] = android_image_preflight.inspect(path)
                    if result["image"].get("ready"):
                        result["detected"]["kind"] = "android_userdata_image"
                        result["detected"]["adapter"] = "filesystem-image"
                        result["detected"]["confidence"] = "high"
                        result["detected"]["analysis_state"] = "CAN_NORMALIZE"
                    elif (result["image"].get("segment_count", 1) == 1 and
                          (result["image"].get("selected_partition") or {}).get("locked")):
                        result["detected"]["kind"] = "android_userdata_locked"
                        result["detected"]["adapter"] = "filesystem-image"
                        result["detected"]["confidence"] = "medium"
                        result["detected"]["analysis_state"] = "LOCKED"
        else:
            limit = _FULL_ENTRY_LIMIT if full_hash else _QUICK_ENTRY_LIMIT
            tree_digest = hashlib.sha256()
            counts = Counter()
            extensions = Counter()
            nested_candidates = []
            nested_suffixes = {".e01", ".dd", ".img", ".raw", ".bin",
                               ".zip", ".7z", ".tar", ".mfc", ".m01", ".mf"}
            manifest_path = _job_dir(job_id) / "manifest.jsonl"
            scan_started = time.monotonic()
            with manifest_path.open("w", encoding="utf-8") as manifest:
                for current, directories, filenames in os.walk(path, followlinks=False):
                    directories[:] = sorted(d for d in directories if not (Path(current) / d).is_symlink())
                    for name in sorted(filenames):
                        if cancelled.is_set():
                            raise _Cancelled()
                        if not full_hash and time.monotonic() - scan_started >= _QUICK_SECONDS:
                            result["inventory_truncated"] = True
                            result["limit_reason"] = "quick scan time budget reached"
                            break
                        item = Path(current) / name
                        if item.is_symlink() or not item.is_file():
                            counts["skipped_nonregular"] += 1
                            continue
                        relative = item.relative_to(path).as_posix()
                        stat = item.stat(follow_symlinks=False)
                        suffix = item.suffix.lower() or "[none]"
                        extensions[suffix] += 1
                        if suffix in nested_suffixes and len(nested_candidates) < 30:
                            nested_candidates.append(relative)
                        record = {"path": relative, "size": stat.st_size, "sha256": None}
                        if full_hash:
                            try:
                                record["sha256"], _ = _hash_file(item, cancelled, advance)
                                tree_digest.update(relative.encode("utf-8", errors="surrogateescape") + b"\0" + record["sha256"].encode() + b"\n")
                            except (OSError, PreflightError) as exc:
                                record["error"] = str(exc)
                                counts["hash_errors"] += 1
                        manifest.write(json.dumps(record, ensure_ascii=True) + "\n")
                        counts["files"] += 1
                        counts["bytes_observed"] += stat.st_size
                        if time.monotonic() - last_write >= 1:
                            result["file_count"] = counts["files"]
                            result["source_size"] = counts["bytes_observed"]
                            _write_job(job_id, result)
                            last_write = time.monotonic()
                        if counts["files"] >= limit:
                            result["inventory_truncated"] = True
                            break
                    if result["inventory_truncated"]:
                        break
            result["manifest_available"] = True
            result["file_count"] = counts["files"]
            result["source_size"] = counts["bytes_observed"]
            result["extension_counts"] = dict(extensions.most_common(30))
            result["nested_candidates"] = nested_candidates
            result["skipped_nonregular"] = counts["skipped_nonregular"]
            result["hash_errors"] = counts["hash_errors"]
            if full_hash and not result["inventory_truncated"] and not counts["hash_errors"]:
                result["tree_manifest_sha256"] = tree_digest.hexdigest()
        if cancelled.is_set():
            raise _Cancelled()
        result["status"] = "partial" if result["inventory_truncated"] or result.get("hash_errors") else "completed"
        result["integrity_status"] = (
            ("verified" if path.is_file() else "manifest_hashed")
            if full_hash and result["status"] == "completed"
            else "incomplete" if full_hash else "not_calculated"
        )
    except _Cancelled:
        result["status"] = "cancelled"
        result["integrity_status"] = "incomplete"
    except Exception as exc:
        result["status"] = "failed"
        result["integrity_status"] = "incomplete"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if password:
            password[:] = b"\0" * len(password)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _write_job(job_id, result)
        finally:
            with _lock:
                _active.pop(job_id, None)


def start_job(candidate_id: str, *, full_hash: bool = False,
              password: str = "", selected_slot: int = 0) -> dict:
    path = _selected(candidate_id)
    if not isinstance(password, str) or len(password) > 1024:
        raise PreflightError("invalid archive password")
    if password and _probe(path)["kind"] not in {"android_backup_encrypted", "seven_zip_container"}:
        raise PreflightError("password is not applicable to this source")
    if not isinstance(selected_slot, int) or isinstance(selected_slot, bool) or not 0 <= selected_slot <= 31:
        raise PreflightError("selected_slot must be an integer from 0 to 31")
    secret = bytearray(password.encode("utf-8")) if password else bytearray()
    with _lock:
        if len(_active) >= 2:
            raise PreflightError("two preflight jobs are already running")
        job_id = uuid.uuid4().hex
        cancelled = threading.Event()
        _active[job_id] = cancelled
    job = {
        "id": job_id, "candidate_id": candidate_id, "name": path.name,
        "source_path": str(path), "status": "queued", "full_hash": full_hash,
        "password_supplied": bool(secret),
        "selected_slot": selected_slot,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bytes_read": 0, "file_count": 0, "source_size": None,
        "inventory_truncated": False, "sha256": None, "tree_manifest_sha256": None,
        "integrity_status": "not_calculated", "manifest_available": False,
    }
    try:
        _write_job(job_id, job)
        threading.Thread(target=_run_job,
                         args=(job_id, path, full_hash, cancelled, secret, selected_slot),
                         daemon=True).start()
    except Exception:
        secret[:] = b"\0" * len(secret)
        with _lock:
            _active.pop(job_id, None)
        raise
    return job


def cancel_job(job_id: str) -> dict:
    _job_dir(job_id)
    with _lock:
        event = _active.get(job_id)
    if event is None:
        raise PreflightError("preflight job is not running")
    event.set()
    return get_job(job_id)
