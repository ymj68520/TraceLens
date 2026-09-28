#!/usr/bin/env python3
"""Build an isolated, field-only frontend candidate outside the live web/dist.

Must run in a fresh network namespace. It never installs dependencies and
never writes to the currently served frontend directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from isolated_target import require_private_loopback_namespace


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_digest() -> str:
    web = ROOT / "web"
    files = [*web.joinpath("src").rglob("*.js"), *web.joinpath("src").rglob("*.jsx"),
             *web.joinpath("src").rglob("*.css"),
             web / "package.json", web / "package-lock.json", web / "vite.config.js"]
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if not path.is_file() or path.is_symlink():
            raise ValueError("frontend source is missing or unsafe")
        digest.update(path.relative_to(web).as_posix().encode() + b"\0" + _sha(path).encode() + b"\n")
    return digest.hexdigest()


def build(output: Path) -> dict:
    netns = require_private_loopback_namespace()
    output = output.absolute()
    if (output == ROOT / "web" / "dist" or output.exists() or output.parent.is_symlink()
            or not output.parent.is_dir() or output.is_relative_to(ROOT / "build" / "data")):
        raise ValueError("output must be a new isolated release directory")
    node_version = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if not node_version.startswith("v22."):
        raise RuntimeError("Node 22 is required for the field frontend build")
    source_sha = _source_digest()
    output.mkdir(mode=0o700)
    marker = output / "INCOMPLETE"
    marker.write_text("Field frontend build has not passed validation\n", encoding="utf-8")
    safe_env = {key: value for key, value in os.environ.items()
                if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "NVM_DIR"}}
    safe_env.update({
        "VITE_FIELD_AUTH": "enabled", "VITE_PYTHON_API_URL": "/python",
        "VITE_CS_API_URL": "/cs-disabled", "VITE_CPP_API_URL": "",
        "VITE_API_BASE_URL": "", "VITE_FIELD_RELEASE_BUILD": "1",
        "npm_config_offline": "true", "npm_config_audit": "false",
    })
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    release_id = "6c-" + commit[:16]
    safe_env["VITE_FIELD_RELEASE_ID"] = release_id
    command = ["npm", "run", "build", "--", "--outDir", str(output / "web")]
    subprocess.run(command, cwd=ROOT / "web", env=safe_env, timeout=300, check=True)
    web_root = output / "web"
    if not (web_root / "index.html").is_file():
        raise RuntimeError("frontend build did not publish index.html")
    assets = {path.relative_to(web_root).as_posix(): _sha(path)
              for path in sorted(web_root.rglob("*")) if path.is_file() and not path.is_symlink()}
    if any(path.endswith(".map") for path in assets):
        raise RuntimeError("field release must not contain JavaScript source maps")
    markers = (b"mock_jwt_token", b"synthetic-browser-user-token", b"test-only-mock", b"phase-e-small")
    if any(marker in path.read_bytes() for path in web_root.rglob("*.js") for marker in markers):
        raise RuntimeError("test-only marker was bundled into the field frontend")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "format": "tracelens-field-frontend-candidate-v1", "mode": "ISOLATED_TEST",
        "instance_identity": "field-frontend-build", "network_namespace": netns,
        "git_commit": commit, "worktree_dirty": bool(dirty),
        "release_id": release_id,
        "source_tree_sha256": source_sha, "node_version": node_version,
        "routing": {"cpp": "same_origin", "python": "/python", "cs": "/cs-disabled"},
        "field_auth": "enabled", "files": assets,
        "publishable": not bool(dirty),
    }
    (web_root / "frontend_build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    marker.unlink()
    return {"output": str(web_root), "source_tree_sha256": source_sha,
            "asset_count": len(assets), "worktree_dirty": bool(dirty),
            "publishable": not bool(dirty)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
