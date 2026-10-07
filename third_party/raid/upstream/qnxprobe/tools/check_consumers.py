#!/usr/bin/env python3
"""Which repositories are carrying an out-of-date copy of a vendored file?

A per-repo vendoring check answers "does my copy match what I recorded". It
cannot answer the question that matters after an upstream release: the file
moved, so who is now behind? Nothing in the upstream repository knows its own
consumers, and nothing in a consumer notices the day upstream changes.

This reads tools/vendoring.json, takes the current bytes of each upstream file,
and compares them against the sha256 every consumer recorded in its own
vendored.json.

    python3 tools/check_consumers.py                    # over the network
    python3 tools/check_consumers.py --local ..         # from checkouts beside this one
    python3 tools/check_consumers.py --summary out.md   # also write a job summary

BEHIND and COULD NOT CHECK are reported separately and exit differently. They
are different results: one says a copy is stale, the other says nothing was
compared, and folding the second into the first turns an unreachable network
into a finding that reads like a defect.

Exit 0 every consumer is current, 1 at least one is behind, 2 nothing was
behind but something could not be checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "vendoring.json")
API = "https://api.github.com/repos/{repo}/contents/{path}"
TIMEOUT = 30


def _token() -> str:
    """A GitHub token from the environment, or "".

    Without one the private repositories in the registry answer 404, which is
    reported as not compared rather than as up to date. A check that cannot see
    half its consumers must say so rather than call them current.
    """
    return (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


class Unavailable(Exception):
    """The thing could not be fetched or read. Not a finding about the copy."""


def _fetch(repo: str, path: str) -> bytes:
    url = API.format(repo=repo, path=path)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        "User-Agent": "qnxprobe-check-consumers",
    })
    token = _token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
            return fh.read()
    except urllib.error.HTTPError as exc:
        hint = "" if token else " (no GH_TOKEN set, so private repositories 404)"
        raise Unavailable(f"{url}: {exc}{hint}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Unavailable(f"{url}: {exc}") from exc


def _read_local(root: str, repo: str, path: str) -> bytes:
    # a checkout is expected to be named after the repository
    where = os.path.join(root, repo.split("/")[-1], path)
    try:
        with open(where, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unavailable(f"{where}: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _recorded(manifest: bytes, name: str) -> dict:
    try:
        doc = json.loads(manifest)
    except ValueError as exc:
        raise Unavailable(f"the manifest is not JSON: {exc}") from exc
    for entry in doc.get("vendored", []):
        if entry.get("name") == name:
            return entry
    raise Unavailable(f"the manifest records no entry named {name!r}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", metavar="DIR",
                    help="read every repository from checkouts under DIR instead of "
                         "over the network")
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--summary", metavar="FILE",
                    help="also write the report to FILE as Markdown")
    args = ap.parse_args()

    with open(args.registry, encoding="utf-8") as fh:
        registry = json.load(fh)

    def get(repo: str, path: str) -> bytes:
        return _read_local(args.local, repo, path) if args.local else _fetch(repo, path)

    behind: list[str] = []
    unknown: list[str] = []
    current: list[str] = []
    rows: list[tuple[str, str, str, str]] = []

    for up in registry["upstreams"]:
        name, repo, path = up["name"], up["repo"], up["file"]
        try:
            want = _sha256(get(repo, path))
        except Unavailable as exc:
            unknown.append(f"{name}: the upstream file could not be read ({exc})")
            rows.append((name, repo, "?", "upstream unreadable"))
            continue
        for consumer in up["consumers"]:
            crepo, cpath = consumer["repo"], consumer["manifest"]
            label = f"{name} in {crepo}"
            try:
                entry = _recorded(get(crepo, cpath), name)
            except Unavailable as exc:
                unknown.append(f"{label}: {exc}")
                rows.append((name, crepo, "?", "not compared"))
                continue
            got = entry.get("sha256", "")
            ver = entry.get("version", "?")
            if got == want:
                current.append(f"{label}: {ver}")
                rows.append((name, crepo, ver, "current"))
            else:
                behind.append(f"{label}: has {ver} ({got[:12] or 'no sha'}), "
                              f"upstream is {want[:12]}")
                rows.append((name, crepo, ver, "**BEHIND**"))

    out = []
    if behind:
        out.append("Consumers carrying an out-of-date copy:\n")
        out += [f"  {b}" for b in behind]
        out.append("")
        out.append("Re-vendor each of those, then update its vendored.json.")
    elif current:
        out.append(f"Every consumer is current ({len(current)} checked).")
    else:
        # nothing was behind because nothing was looked at, which is not the
        # same sentence and must not be printed as though it were
        out.append("Nothing was compared.")
    if unknown:
        out.append("")
        out.append("Not compared, so nothing is claimed about these:\n")
        out += [f"  {u}" for u in unknown]
    report = "\n".join(out)
    print(report)

    if args.summary:
        md = ["# Vendored copies", "",
              "| file | consumer | version | state |", "| --- | --- | --- | --- |"]
        md += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
        md += ["", "```", report, "```"]
        with open(args.summary, "w", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")

    if behind:
        return 1
    return 2 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
