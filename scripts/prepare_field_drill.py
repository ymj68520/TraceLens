#!/usr/bin/env python3
"""Stage an isolated 6C runtime drill copy; never publish this layout.

The Python venv is a read-only external symlink to the already installed
runtime. That is useful for a no-download drill but is NOT a releasable,
versioned dependency bundle. No data, secrets, mock server or test account is
copied into this layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path

from isolated_target import require_private_loopback_namespace

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = ("android_container_pipeline_cli.py", "android_image_reader_bridge.py")
PINNED_TOOLS = (".deps/qnxprobe/qnxprobe.py", ".deps/qnxprobe/ewfprobe.py",
                ".deps/aosp-android10-r36/bin/lp_inventory",
                ".deps/aosp-android10-r36/bin/lpunpack",
                ".deps/aosp-android10-r36/bin/liblp.so", ".deps/aosp-android10-r36/bin/lpmake")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(root: Path, relative: str) -> None:
    source = ROOT / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError("drill runtime source file is missing or unsafe")
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def stage(frontend: Path, binary: Path, output: Path, release_id: str) -> dict:
    netns = require_private_loopback_namespace()
    output = output.absolute()
    if (not re.fullmatch(r"[A-Za-z0-9-]{12,80}", release_id) or output.exists()
            or output.parent.is_symlink() or not output.parent.is_dir()):
        raise ValueError("drill output or release ID is unsafe")
    frontend = frontend.resolve(strict=True)
    binary = binary.resolve(strict=True)
    if (not (frontend / "frontend_build_manifest.json").is_file()
            or binary.is_symlink() or not binary.is_file()):
        raise ValueError("drill requires an attested frontend and isolated C++ binary")
    output.mkdir(mode=0o700)
    (output / "INCOMPLETE").write_text("Not a production release\n", encoding="utf-8")
    source_package = ROOT / "python_service/httpserver"
    shutil.copytree(source_package, output / "python_service/httpserver",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.log"))
    release_info = output / "python_service/httpserver/release_info.py"
    release_info.write_text(
        f'"""Baked identity of this isolated drill package."""\nRELEASE_ID = {release_id!r}\nSOURCE_COMMIT = "DRILL_ONLY"\nSOURCE_TREE_SHA256 = "DRILL_ONLY"\nRELEASE_LAYOUT_VERSION = "6c-v1"\n',
        encoding="utf-8")
    for relative in ("python_service/requirements.txt", "python_service/httpserver/requirements.txt",
                     "THIRD_PARTY_LICENSES.md", *PINNED_TOOLS):
        _copy(output, relative)
    for script in RUNTIME_SCRIPTS:
        _copy(output, "scripts/" + script)
    binary_dest = output / "build/forensic_analyzer"
    binary_dest.parent.mkdir(parents=True)
    shutil.copy2(binary, binary_dest)
    shutil.copytree(frontend, output / "build/web/dist")
    venv = output / "python_service/.venv"
    venv.symlink_to((ROOT / "python_service/.venv").resolve(), target_is_directory=True)
    files = {path.relative_to(output).as_posix(): _sha(path)
             for path in output.rglob("*") if path.is_file() and not path.is_symlink()
             and path.name not in {"INCOMPLETE", "drill_manifest.json"}}
    manifest = {"format": "tracelens-6c-drill-v1", "release_id": release_id,
                "network_namespace": netns, "files_sha256": files,
                "external_python_venv": True, "publishable": False,
                "reason": "DIRTY_WORKTREE_AND_EXTERNAL_MUTABLE_VENV"}
    (output / "drill_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    (output / "INCOMPLETE").unlink()
    return {"release_id": release_id, "output": str(output), "file_count": len(files),
            "publishable": False, "external_python_venv": True}


def freeze(frontend: Path, binary: Path, output: Path, wheelhouse: Path) -> dict:
    """Stage a fixed candidate and rebuild its Python environment with no network.

    The legacy drill remains explicitly non-publishable. This path never uses
    its external venv link, data or mutable modules. Source commit and build
    fingerprint are checked before copying any artifact.
    """
    from field_build_identity import identity
    netns = require_private_loopback_namespace()
    fixed = identity()
    output = output.absolute()
    if output.exists() or output.parent.is_symlink() or not output.parent.is_dir():
        raise ValueError('candidate runtime must be a new safe directory')
    version = subprocess.check_output([str(binary.resolve(strict=True)), '--version'], text=True)
    if any(value not in version for value in (fixed['release_id'], fixed['source_commit'], fixed['source_tree_sha256'])):
        raise ValueError('C++ embedded build identity does not match fixed candidate')
    web = json.loads((frontend / 'frontend_build_manifest.json').read_text())
    if web.get('git_commit') != fixed['source_commit'] or web.get('release_id') != fixed['release_id'] or web.get('worktree_dirty'):
        raise ValueError('frontend does not correspond to fixed candidate')
    material = json.loads((ROOT / 'deploy/field/python-linux-cp310-x86_64.material.json').read_text())
    wheelhouse = wheelhouse.resolve(strict=True)
    for item in material['artifacts']:
        file = wheelhouse / item['filename']
        if file.is_symlink() or file.parent != wheelhouse or _sha(file) != item['sha256']:
            raise ValueError('offline Python artifact is missing or changed')
    output.mkdir(mode=0o700)
    marker = output / 'INCOMPLETE'
    marker.write_text('Candidate staging is incomplete\n')
    shutil.copytree(ROOT / 'python_service/httpserver', output / 'python_service/httpserver',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.db', '*.log'))
    for name in ('extractor_mapping.json','artifact_whitelist.json'):
        _copy(output, 'python_service/config/' + name)
    (output / 'python_service/httpserver/_build_identity.py').write_text(
        '# Generated from fixed source; imported once by the running service.\n'
        + ''.join(f'{key.upper()} = {fixed[key]!r}\n' for key in ('release_id','source_commit','source_tree_sha256')))
    for script in RUNTIME_SCRIPTS:
        _copy(output, 'scripts/' + script)
    for name in ('THIRD_PARTY_LICENSES.md', *PINNED_TOOLS):
        _copy(output, name)
    for name in ('.deps/qnxprobe/LICENSE', '.deps/qnxprobe/LICENSE-ewfprobe', '.deps/qnxprobe/vendored.json'):
        _copy(output, name)
    for name in ('.deps/aosp-android10-r36/core/NOTICE', '.deps/aosp-android10-r36/pinned-source.sha256'):
        _copy(output, name)
    for line in (ROOT / '.deps/aosp-android10-r36/pinned-source.sha256').read_text().splitlines():
        digest, relative = line.split('  ',1)
        path = ROOT / '.deps/aosp-android10-r36' / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or _sha(path) != digest:
            raise ValueError('pinned public tool source changed before staging')
        _copy(output,'.deps/aosp-android10-r36/' + relative)
    shutil.copytree(ROOT / 'deploy/field', output / 'deploy/field')
    dest = output / 'build/forensic_analyzer'
    dest.parent.mkdir(parents=True)
    shutil.copy2(binary, dest)
    shutil.copytree(frontend, output / 'build/web/dist')
    venv = output / 'python_service/.venv'
    subprocess.run([sys.executable, '-m', 'venv', '--copies', str(venv)], check=True)
    executable = venv / 'bin/python'
    safe = {k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR'}}
    safe.update({'PIP_NO_INDEX':'1','PIP_CONFIG_FILE':os.devnull, 'PYTHONNOUSERSITE':'1'})
    install = [str(executable), '-m', 'pip', 'install', '--no-index', '--no-cache-dir', '--require-hashes',
               '--find-links', str(wheelhouse), '-r', str(output / 'deploy/field/python-linux-cp310-x86_64.lock')]
    subprocess.run(install, env=safe, check=True)
    subprocess.run([str(executable), '-m', 'pip', 'check'], env=safe, check=True)
    code = "import importlib.metadata as m,json,sys,platform; from packaging.utils import canonicalize_name; print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'python':platform.python_version(),'versions':{canonicalize_name(d.metadata['Name']):d.version for d in m.distributions()}}))"
    checked = json.loads(subprocess.check_output([str(executable), '-c', code], env=safe, text=True))
    expected = {x['name']:x['version'] for x in material['artifacts']}
    if checked['versions'] != expected or 'include-system-site-packages = false' not in (venv / 'pyvenv.cfg').read_text():
        raise ValueError('fresh offline environment differs from the declared dependency lock')
    validation = {'status':'OFFLINE_REBUILD_VERIFIED','network_namespace':netns,'release_id':fixed['release_id'],
        'source_commit':fixed['source_commit'],'python':checked['python'],'package_count':len(expected),
        'lock_sha256':_sha(output / 'deploy/field/python-linux-cp310-x86_64.lock'),
        'wheel_hashes_verified':True,'pip_check':'PASS','system_site_packages':False,
        'old_venv_used':False,'network_fallback':False}
    (output / 'python_offline_validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    marker.unlink()
    return {**fixed, 'output':str(output), 'python_validation':validation, 'production_switched':False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--freeze", action="store_true", help="fixed clean candidate with a newly offline-installed venv")
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    if args.freeze:
        if not args.wheelhouse:
            parser.error('--freeze requires a verified wheelhouse')
        from field_build_identity import identity
        if args.release_id != identity()['release_id']:
            parser.error('release-id does not match fixed candidate')
        print(json.dumps(freeze(args.frontend, args.binary, args.output, args.wheelhouse),ensure_ascii=False))
    else:
        print(json.dumps(stage(args.frontend, args.binary, args.output, args.release_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
