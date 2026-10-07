"""RAID prepared-image admission for the existing Task workflow only."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from ..config import get_data_root, get_project_root

CODE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CODE_ROOT))
from raid.core import RaidError, confined_open
from raid.export import write_json

_ID = re.compile(r"[0-9a-f]{32}\Z")
_lock = threading.RLock()
_active = {}
_cancel = {}


def inbox():
    root = Path(os.environ.get("TRACELENS_RAID_INBOX") or get_project_root().parent / "RAID").resolve()
    if root == Path(root.anchor): raise RaidError("BROAD_RAID_INBOX_FORBIDDEN")
    return root


def jobs_root():
    return get_data_root() / "raid_intake"


def catalog():
    root = inbox()
    if not root.is_dir(): return {"groups": [], "warnings": ["RAID_INBOX_NOT_CONFIGURED"]}
    groups = defaultdict(list)
    count = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if not (base / d).is_symlink() and len(base.relative_to(root).parts) < 8]
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or path.suffix.lower() not in (".img", ".raw", ".dd", ".bin", ".hdd"): continue
            relative = path.relative_to(root).as_posix()
            with confined_open(root, relative) as source: size = os.fstat(source.fileno()).st_size
            identifier = hashlib.sha256((str(root) + "\0" + relative).encode()).hexdigest()[:24]
            groups[base.relative_to(root).as_posix()].append({"id": identifier, "name": name, "size": size})
            count += 1
            if count > 1000: raise RaidError("RAID_CATALOG_LIMIT")
    return {"groups": [{"name": name, "files": files} for name, files in sorted(groups.items())],
            "max_members": 32, "formats": ["RAW"], "warnings": []}


def _selected(ids):
    if not isinstance(ids, list) or not 2 <= len(ids) <= 32 or \
            any(not isinstance(i, str) or not re.fullmatch(r"[0-9a-f]{24}", i) for i in ids) or len(set(ids)) != len(ids):
        raise RaidError("INVALID_RAID_SELECTION")
    entries = {item["id"]: group["name"] + "/" + item["name"] if group["name"] != "." else item["name"]
               for group in catalog()["groups"] for item in group["files"]}
    if any(i not in entries for i in ids): raise RaidError("SELECTED_RAID_MEMBER_UNAVAILABLE")
    members = [{"files": [entries[i]]} for i in ids]
    for member in members:
        with confined_open(inbox(), member["files"][0]): pass
    return members


def job_dir(job_id):
    if not isinstance(job_id, str) or not _ID.fullmatch(job_id): raise RaidError("INVALID_RAID_JOB_ID")
    path = jobs_root() / job_id
    if path.is_symlink() or path.parent.is_symlink(): raise RaidError("RAID_JOB_PATH_ESCAPE")
    return path


def _read(job_id):
    path = job_dir(job_id) / "job.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024**2:
        raise RaidError("RAID_JOB_UNAVAILABLE")
    return json.loads(path.read_text())


def _store(job_id, value):
    # Multiple status updates use atomic replacements; sources are never edited.
    path = job_dir(job_id) / "job.json"
    temporary = path.with_suffix(".new")
    with temporary.open("w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=True); out.flush(); os.fsync(out.fileno())
    os.replace(temporary, path)


def public(job_id, owner):
    with _lock:
        job = _read(job_id)
        if job["owner"] != owner: raise PermissionError("RAID job belongs to another principal")
    keys = ("id", "status", "message", "error_code", "inference", "integrity_status", "task_source", "member_count")
    return {key: job[key] for key in keys if key in job}


def _worker(job_id, action, data):
    process = None
    try:
        input_file = job_dir(job_id) / (action + "-input.json")
        write_json(input_file, data)
        with _lock:
            job = _read(job_id); job.update(status="running", message="识别布局…" if action == "infer" else "准备系统镜像…")
            _store(job_id, job)
        env = {k: v for k, v in os.environ.items() if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
        # Output files are private and bounded before parsing; no stderr body in normal logs.
        output_file = job_dir(job_id) / (action + "-output.json")
        error_file = job_dir(job_id) / (action + "-error.private.json")
        with output_file.open("xb") as out, error_file.open("xb") as err:
            process = subprocess.Popen([sys.executable, str(CODE_ROOT / "scripts/raid_web_worker.py"), action, str(input_file)],
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
            deadline = time.monotonic() + (240 if action == "infer" else 1900)
            while process.poll() is None:
                if _cancel[job_id].is_set() or time.monotonic() > deadline:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                    raise RaidError("RAID_JOB_CANCELLED" if _cancel[job_id].is_set() else "RAID_JOB_TIMEOUT")
                time.sleep(0.1)
        if process.returncode:
            code = "RAID_WORKER_FAILED"
            if error_file.stat().st_size < 4096:
                try: code = json.loads(error_file.read_text())["code"]
                except (ValueError, KeyError): pass
            raise RaidError(code)
        if output_file.stat().st_size > 8 * 1024**2: raise RaidError("RAID_WORKER_OUTPUT_LIMIT")
        result = json.loads(output_file.read_text())
        with _lock:
            job = _read(job_id)
            if _cancel[job_id].is_set(): raise RaidError("RAID_JOB_CANCELLED")
            if action == "infer":
                job.update(status="awaiting_confirmation", message="选择并确认布局", inference=result)
            else:
                package = Path(result["package_directory"]).resolve(strict=True)
                if package.parent != (job_dir(job_id) / "packages").resolve(strict=True):
                    raise RaidError("RAID_PACKAGE_ESCAPES_JOB")
                job.update(status="ready", message="系统镜像准备完成", integrity_status=result["status"],
                    package_directory=str(package), image_path=str(package / "logical.img"),
                    image_sha256=result["derived_image"]["sha256"], manifest_sha256=result["manifest_sha256"],
                    manifest_file_sha256=hashlib.sha256((package / "raid_manifest.json").read_bytes()).hexdigest(),
                    source_root=result["source_root"], member_sha256=result["source_sha256"],
                    display_name=f"RAID{result['layout']['level']}（{job['member_count']} 成员）")
                job["task_source"] = {"image_source": "raid", "android_source": "tsk", "image_path": job["image_path"],
                                      "raid_job_id": job_id, "raid_manifest_sha256": job["manifest_sha256"],
                                      "raid_allow_partial": job["allow_partial"]}
            _store(job_id, job)
    except Exception as exc:
        with _lock:
            job = _read(job_id)
            job.update(status="cancelled" if _cancel[job_id].is_set() else "failed",
                       error_code=str(exc) if isinstance(exc, RaidError) else "RAID_PREPARATION_FAILED", message="准备未完成")
            _store(job_id, job)
    finally:
        if process is not None and process.poll() is None: process.kill(); process.wait()
        with _lock: _active.pop(job_id, None)


def start(ids, owner):
    members = _selected(ids)
    job_id = uuid.uuid4().hex
    data = {"source_root": str(inbox()), "members": members}
    with _lock:
        if len(_active) >= 2: raise RaidError("RAID_WORKER_CAPACITY")
        root = jobs_root(); root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = job_dir(job_id); path.mkdir(mode=0o700)
        _store(job_id, {"id": job_id, "owner": owner, "status": "queued", "member_count": len(members),
                        "selection": data, "allow_partial": False})
        _cancel[job_id] = threading.Event()
        thread = threading.Thread(target=_worker, args=(job_id, "infer", data), daemon=True)
        _active[job_id] = thread; thread.start()
    return public(job_id, owner)


def prepare(job_id, candidate_id, owner, *, allow_partial=False):
    with _lock:
        job = _read(job_id)
        if job["owner"] != owner: raise PermissionError("RAID job belongs to another principal")
        if job["status"] != "awaiting_confirmation" or job_id in _active: raise RaidError("RAID_JOB_NOT_CONFIRMABLE")
        if len(_active) >= 2: raise RaidError("RAID_WORKER_CAPACITY")
        inference = job["inference"]
        if inference["status"] not in ("UNIQUE_STRUCTURAL_CANDIDATE", "AMBIGUOUS"):
            raise RaidError("RAID_INFERENCE_NOT_CONFIRMED")
        chosen = next((c for c in inference["candidates"] if c["candidate_id"] == candidate_id), None)
        if chosen is None: raise RaidError("INVALID_RAID_CANDIDATE")
        output = job_dir(job_id) / "packages"; output.mkdir(mode=0o700)
        data = {**job["selection"], "candidate": chosen, "mode": inference.get("mode", "raw"),
                "source_revision": inference["source_revision"], "allow_partial": allow_partial,
                "output_root": str(output), "max_bytes": 1024**3}
        job.update(status="queued", allow_partial=allow_partial, chosen_candidate=chosen); _store(job_id, job)
        _cancel[job_id] = threading.Event()
        thread = threading.Thread(target=_worker, args=(job_id, "prepare", data), daemon=True)
        _active[job_id] = thread; thread.start()
    return public(job_id, owner)


def cancel(job_id, owner):
    public(job_id, owner)
    with _lock:
        if job_id in _active: _cancel[job_id].set()
    return public(job_id, owner)
