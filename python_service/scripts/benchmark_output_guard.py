"""Exclusive-create output guard for benchmark/preflight scripts (RCA-2A.2c).

Output-path contract (directive section 4):
- the caller names the output path explicitly on every invocation;
- an existing file is NEVER overwritten or truncated (atomic
  O_CREAT|O_EXCL exclusive create);
- a failed write leaves any pre-existing file byte-identical (the guard
  never opens an existing path for writing);
- no API key or auth material passes through this module — it records
  nothing and accepts nothing but a filesystem path.
"""

from __future__ import annotations

import os
from pathlib import Path


class OutputPathError(RuntimeError):
    """The requested output path violates the no-clobber contract."""


def exclusive_output_file(path: str | os.PathLike[str]):
    """Open ``path`` for writing via atomic exclusive create.

    Returns an open text file object (mode 0600).  Raises OutputPathError
    when the path already exists — the caller must choose a fresh path;
    the pre-existing file is never opened for writing, so a failed or
    aborted run can never modify it.
    """
    target = Path(path)
    if target.exists():
        raise OutputPathError(
            f"refusing to overwrite existing artifact: {target} — "
            "pass a fresh --out path"
        )
    parent = target.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


__all__ = ["OutputPathError", "exclusive_output_file"]
