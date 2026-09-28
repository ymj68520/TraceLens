#!/usr/bin/env python3
"""Create a redacted 6C release-candidate inventory without packaging data.

Source and dependency hashes describe the current workspace; a dirty tree is
never marked publishable. This tool does not commit, deploy or restart anything.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from field_frontend_build import _source_digest as frontend_source_digest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PREFIXES = ("src/", "include/", "python_service/httpserver/", "web/src/",
                   "scripts/", "deploy/field/", "tests/")
SOURCE_EXACT = ("CMakeLists.txt", "web/package.json", "web/package-lock.json",
                "web/vite.config.js", "python_service/requirements.txt",
                "python_service/httpserver/requirements.txt", "THIRD_PARTY_LICENSES.md")
TOOLS = (".deps/qnxprobe/qnxprobe.py", ".deps/qnxprobe/ewfprobe.py",
         ".deps/aosp-android10-r36/bin/lp_inventory",
         ".deps/aosp-android10-r36/bin/lpunpack",
         ".deps/aosp-android10-r36/bin/liblp.so", "/usr/bin/simg2img")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip()


def _sources() -> tuple[str, int]:
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, timeout=30, check=True).stdout
    names = [name.decode("utf-8", "surrogateescape") for name in listed.split(b"\0") if name]
    digest = hashlib.sha256()
    count = 0
    for name in sorted(set(names)):
        if name not in SOURCE_EXACT and not name.startswith(SOURCE_PREFIXES):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 10 * 1024 * 1024:
            continue
        digest.update(name.encode("utf-8", "surrogateescape") + b"\0" + _sha(path).encode() + b"\n")
        count += 1
    return digest.hexdigest(), count


def _dirty() -> dict:
    raw = subprocess.run(["git", "status", "--porcelain", "-z"], cwd=ROOT,
                         capture_output=True, timeout=30, check=True).stdout
    entries = [item.decode("utf-8", "replace") for item in raw.split(b"\0") if item]
    groups = collections.Counter()
    for entry in entries:
        name = entry[3:]
        groups[name.split("/", 1)[0]] += 1
    return {"count": len(entries), "top_level_groups": dict(groups)}


def _dependencies(python_bin: Path) -> dict:
    if not python_bin.is_file():
        return {"status": "MISSING_PINNED_PYTHON_RUNTIME"}
    result = subprocess.run([str(python_bin), "-m", "pip", "freeze", "--local", "--disable-pip-version-check"],
                            capture_output=True, text=True, timeout=60, check=False,
                            env={key: value for key, value in os.environ.items()
                                 if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}})
    if result.returncode:
        return {"status": "DEPENDENCY_INVENTORY_UNAVAILABLE"}
    lines = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    if any("://" in line or line.startswith("-e ") or "@ file:" in line for line in lines):
        return {"status": "DEPENDENCY_LOCK_HAS_UNSAFE_OR_UNPINNED_LOCATION"}
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
    return {"status": "INVENTORIED_NOT_OFFLINE_REINSTALLED", "package_count": len(lines),
            "freeze_sha256": digest, "exact_versions": lines}


def manifest(frontend: Path, cpp_binary: Path, python_bin: Path, *, runtime_root: Path | None = None,
             regression_result: Path | None = None) -> dict:
    commit = _run("git", "rev-parse", "HEAD")
    dirty = _dirty()
    source_sha, source_count = _sources()
    frontend_manifest = frontend / "frontend_build_manifest.json"
    web = json.loads(frontend_manifest.read_text(encoding="utf-8")) if frontend_manifest.is_file() else {}
    binary = (_sha(cpp_binary) if cpp_binary.is_file() and not cpp_binary.is_symlink() else None)
    tool_hashes = {name: _sha(Path(name) if name.startswith("/") else ROOT / name)
                   for name in TOOLS if (Path(name) if name.startswith("/") else ROOT / name).is_file()}
    config_hashes = {path.relative_to(ROOT).as_posix(): _sha(path)
                     for path in sorted((ROOT / "deploy/field").glob("*.example")) if path.is_file()}
    dependencies = _dependencies(python_bin)
    release_id = "6c-" + commit[:16]
    blockers = []
    if len(tool_hashes) != len(TOOLS):
        blockers.append('PINNED_TOOL_INVENTORY_INCOMPLETE')
    linked = {}
    if cpp_binary.is_file():
        import re
        result = subprocess.run(['ldd', str(cpp_binary)], capture_output=True, text=True, check=True)
        if 'not found' in result.stdout:
            blockers.append('CPP_DYNAMIC_LIBRARY_MISSING')
        for name in re.findall(r'(/[^\s()]+)', result.stdout):
            path = Path(name)
            if path.is_file():
                linked[str(path.resolve())] = _sha(path.resolve())
        if any('/mnt/d/' in path or '/home/ymj68520/projects/' in path for path in linked):
            blockers.append('CPP_DEPENDS_ON_ORIGINAL_WORKSPACE')
    if dirty["count"]:
        blockers.append("DIRTY_WORKTREE_OWNERSHIP_UNRESOLVED")
    if not binary:
        blockers.append("ISOLATED_CPP_BINARY_MISSING")
    if web.get("source_tree_sha256") is None or web.get("routing") != {
        "cpp": "same_origin", "python": "/python", "cs": "/cs-disabled"}:
        blockers.append("FIELD_FRONTEND_BUILD_UNVERIFIED")
    elif web.get("source_tree_sha256") != frontend_source_digest():
        blockers.append("FRONTEND_SOURCE_DRIFT_AFTER_BUILD")
    cache = cpp_binary.parent / "CMakeCache.txt"
    if not cache.is_file():
        cache = cpp_binary.parent.parent / "CMakeCache.txt"
    baked = None
    if cache.is_file():
        baked = next((line.split("=", 1)[1] for line in cache.read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.startswith("TRACELENS_RELEASE_ID:STRING=")), None)
    if binary and baked != release_id:
        blockers.append("CPP_RELEASE_ID_MISMATCH")
    offline = {}
    package_files = {}
    regression = {}
    if runtime_root and (runtime_root / 'python_offline_validation.json').is_file():
        offline = json.loads((runtime_root / 'python_offline_validation.json').read_text())
    if offline.get('status') != 'OFFLINE_REBUILD_VERIFIED' or offline.get('source_commit') != commit:
        blockers.append('PYTHON_RUNTIME_NOT_VERSIONED_OR_OFFLINE_REBUILT')
    else:
        code = "from httpserver.release_info import RELEASE_ID,SOURCE_COMMIT,SOURCE_TREE_SHA256; import json; print(json.dumps([RELEASE_ID,SOURCE_COMMIT,SOURCE_TREE_SHA256]))"
        loaded = subprocess.check_output([str(python_bin), '-c', code], cwd=runtime_root / 'python_service',
            env={'PATH':os.environ.get('PATH',''), 'PYTHONPATH':str(runtime_root / 'python_service'),
                 'PYTHONNOUSERSITE':'1'}, text=True)
        if json.loads(loaded) != [release_id,commit,source_sha]:
            blockers.append('PYTHON_BAKED_IDENTITY_MISMATCH')
        dependencies['status'] = 'OFFLINE_REBUILD_VERIFIED'
    if binary:
        embedded = subprocess.check_output([str(cpp_binary), '--version'], text=True)
        if any(x not in embedded for x in (release_id,commit,source_sha)):
            blockers.append('CPP_EMBEDDED_IDENTITY_MISMATCH')
    if web.get('release_id') != release_id or web.get('git_commit') != commit:
        blockers.append('FRONTEND_RELEASE_ID_MISMATCH')
    if regression_result and regression_result.is_file():
        regression = json.loads(regression_result.read_text())
    if regression.get('status') != 'PASS' or regression.get('source_commit') != commit:
        blockers.append('FROZEN_CANDIDATE_REGRESSION_PENDING')
    if runtime_root:
        if (runtime_root / 'INCOMPLETE').exists():
            blockers.append('RUNTIME_PACKAGE_INCOMPLETE')
        for path in sorted(runtime_root.rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                relative = path.relative_to(runtime_root).as_posix()
                if relative not in {'release_manifest.json','package.sha256.json'}:
                    package_files[relative] = _sha(path)
        if any(path.suffix in {'.db','.img','.log'} or path.name == '.env' for path in runtime_root.rglob('*') if path.is_file()):
            blockers.append('RUNTIME_HAS_FORBIDDEN_DATA')
    ready = not blockers
    return {"format": "tracelens-field-release-candidate-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "release_id": release_id, "git_commit": commit, "dirty": dirty,
            "source_tree_sha256": source_sha, "source_file_count": source_count,
            "cpp_binary_sha256": binary, "cpp_binary_path_class": "isolated_candidate" if binary else "missing",
            "cpp_configured_release_id": baked,
            "frontend_build_sha256": _sha(frontend_manifest) if frontend_manifest.is_file() else None,
            "frontend_index_sha256": (web.get("files") or {}).get("index.html"),
            "frontend_source_tree_sha256": web.get("source_tree_sha256"),
            "frontend_routing": web.get("routing"),
            "python_dependencies": dependencies, "toolchain_sha256": tool_hashes,
            'cpp_dynamic_libraries_sha256':linked,
            "deployment_templates_sha256": config_hashes,
            "database_compatibility": {"investigation_read": [7, 8],
                                       "investigation_write": [8],
                                       "external_html_records": "independent records.db",
                                       "r2_envelopes_read": [1, 2, 3]},
            'python_offline_validation':offline, 'candidate_regression':regression,
            'package_files_sha256':package_files,
            'source_scope_confirmed':not dirty['count'], 'candidate_identity_fixed':not dirty['count'],
            'package_engineering_ready':ready, 'production_quiescence_confirmed':False,
            'cutover_approved':False, 'production_switched':False,
            'local_model_validation':'LOCAL_MODEL_VALIDATION_REQUIRED',
            'real_sample_validation':'REAL_SAMPLE_REQUIRED',
            'publishable_semantics':'legacy deployment authorization flag; never true from package readiness alone',
            'production_gate_blockers':['CUTOVER_NOT_APPROVED','STALE_PREFLIGHT_RECONCILIATION_PENDING','RUNNING_UNIT_EGRESS_NOT_VERIFIED'],
            "publishable": False, "blockers": blockers}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--cpp-binary", type=Path, required=True)
    parser.add_argument("--python-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--regression-result', type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.parent.is_symlink() or not args.output.parent.is_dir():
        parser.error("output must be a new file in an existing safe directory")
    result = manifest(args.frontend, args.cpp_binary, args.python_bin,
                      runtime_root=args.runtime_root,regression_result=args.regression_result)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"release_id": result["release_id"], "publishable": result["publishable"],
                      "blockers": result["blockers"], "source_tree_sha256": result["source_tree_sha256"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
