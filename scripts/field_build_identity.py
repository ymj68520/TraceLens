#!/usr/bin/env python3
"""Compute fixed build inputs from a clean candidate, including worktree .git files."""
import argparse
import json
import subprocess
from pathlib import Path
from android_release_manifest import ROOT, _sources

def identity():
    # git -C supports both a repository directory and a worktree .git file.
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('fixed build identity requires a clean candidate commit')
    digest, count = _sources()
    return {'release_id': '6c-' + commit[:16], 'source_commit': commit,
            'source_tree_sha256': digest, 'source_file_count': count}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error('do not overwrite an existing build identity')
    d = identity()
    a.output.write_text(json.dumps(d, indent=2) + '\n')
    print(json.dumps(d))
