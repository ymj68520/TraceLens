#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch full tracked upstream sources at explicit commits, never update in place.

Source retrieval is an explicit development operation, NOT a service startup hook.
`verify` works offline and rejects missing, modified or added upstream files.
No upstream build script is executed by this tool.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1] / "third_party" / "raid"


def inventory(root: Path) -> dict:
    files = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if name == "SOURCE.json":
            continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("UPSTREAM_SYMLINK_ESCAPE")
            files[name] = {"symlink": str(path.readlink())}
        elif path.is_file():
            files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return files


def verify(project: dict) -> dict:
    target = ROOT / "upstream" / project["name"]
    manifest = json.loads((target / "SOURCE.json").read_text())
    if any(manifest.get(key) != project[key] for key in ("name", "url", "commit")):
        raise ValueError("SOURCE_PIN_MISMATCH")
    if inventory(target) != manifest["files"]:
        raise ValueError("SOURCE_BYTES_CHANGED")
    return {"name": project["name"], "commit": project["commit"], "files": len(manifest["files"])}


def fetch(project: dict) -> dict:
    target = ROOT / "upstream" / project["name"]
    if target.exists():
        return verify(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tracelens-raid-upstream-") as temp:
        checkout = Path(temp) / "git"
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "fetch", "--depth=1", project["url"], project["commit"]], check=True)
        actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "FETCH_HEAD"], text=True).strip()
        if actual != project["commit"]:
            raise ValueError("UPSTREAM_COMMIT_MISMATCH")
        archive = Path(temp) / "source.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "-C", str(checkout), "archive", actual], stdout=output, check=True)
        with tarfile.open(archive) as source:
            members = source.getmembers()
            for item in members:
                relative = Path(item.name)
                if relative.is_absolute() or ".." in relative.parts or item.isdev() or item.islnk():
                    raise ValueError("UNSAFE_UPSTREAM_ARCHIVE")
                if item.issym():
                    resolved = (target / relative.parent / item.linkname).resolve()
                    if not resolved.is_relative_to(target.resolve()):
                        raise ValueError("UPSTREAM_SYMLINK_ESCAPE")
            target.mkdir()
            source.extractall(target, members=members)
        manifest = {**project, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "files": inventory(target)}
        (target / "SOURCE.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return verify(project)


def bundle(projects: list[dict], name="sources.bundle.tar.gz") -> dict:
    """Full source distribution, including files ignored by upstream Git rules."""
    for project in projects:
        verify(project)
    if Path(name).name != name or not name.endswith(".tar.gz"):
        raise ValueError("INVALID_SOURCE_BUNDLE_NAME")
    archive = ROOT / name
    with archive.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|") as output:
                def stable(info):
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    return info
                output.add(ROOT / "sources.lock.json", arcname="sources.lock.json", filter=stable)
                for project in projects:
                    output.add(ROOT / "upstream" / project["name"],
                               arcname=f"upstream/{project['name']}", filter=stable)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(name.removesuffix(".tar.gz") + ".sha256").write_text(f"{digest}  {name}\n")
    return {"archive": str(archive), "sha256": digest, "bytes": archive.stat().st_size,
            "snapshots": len(projects), "status": "VERIFIED_LOCAL_SOURCE_DISTRIBUTION"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "verify", "bundle"))
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--bundle-name", default="sources.bundle.tar.gz")
    args = parser.parse_args()
    projects = json.loads((ROOT / "sources.lock.json").read_text())["projects"]
    selected = [p for p in projects if not args.project or p["name"] in args.project]
    if args.project and set(args.project) != {p["name"] for p in selected}:
        parser.error("unknown project")
    if args.action == "bundle":
        if args.project:
            parser.error("source distribution must include every pinned project")
        print(json.dumps(bundle(projects, args.bundle_name), indent=2))
        return
    function = fetch if args.action == "fetch" else verify
    print(json.dumps([function(p) for p in selected], indent=2))


if __name__ == "__main__":
    main()
