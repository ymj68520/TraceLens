#!/usr/bin/env python3
"""Thin CLI shim for the SQLite → RocksDB migration (SPEC §8 R1/R6)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_service"))

from storage.sqlite_migrate import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
