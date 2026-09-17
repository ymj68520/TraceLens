"""RocksDB mirror reader for forensic stores (mvp-phase1-acceptance SPEC §8 R4).

Reads the whole-database mirror produced by the C++ ``SqliteRocksMirror`` or
the Python migration tool: one column family per table, rows keyed by
big-endian rowid (or ``pk:`` JSON key for WITHOUT ROWID tables), values are
canonical JSON rows (``sqlite_migrate.encode_value``), ``_meta`` carries
DDL/columns/keying per table.

This module never writes; it is the Python read-side counterpart of the C++
``RocksRawReader``. The two sides cannot open each other's engine files
(rocksdict pins comparator "rocksdict", standard librocksdb uses
BytewiseComparator), so a store written by C++ must be read by C++ and vice
versa — the shared contract is the row byte format, not the engine file.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    from rocksdict import Rdict, Options
    _HAS_ROCKSDB = True
except ImportError:  # pragma: no cover - bare environments
    _HAS_ROCKSDB = False

META_CF = "_meta"


class MirrorNotFound(RuntimeError):
    """Raised when the path is not a mirrored store — callers fall back to SQLite."""


def mirrored_path_for(db_path: str | Path) -> Path:
    """<name>.db → <name>.rocks sibling, matching the C++ mirror layout."""
    p = Path(db_path)
    return p.with_suffix(".rocks")


def _decode_rowid(key: bytes) -> Optional[int]:
    if len(key) == 8 and key[0] < 0x80:
        return struct.unpack(">Q", key)[0]
    return None


class RocksMirrorReader:
    """Read-only accessor over a mirrored forensic store."""

    def __init__(self, rocks_path: str | Path):
        if not _HAS_ROCKSDB:
            raise MirrorNotFound("rocksdict is not installed")
        path = Path(rocks_path)
        if not (path.is_dir() and (path / "CURRENT").exists()):
            raise MirrorNotFound(f"no mirrored store at {path}")
        options = Options()
        options.create_if_missing(False)
        try:
            # rocksdict requires every family on disk to be declared at open
            # (including default and _meta) — list_cf + open each.
            names = Rdict.list_cf(str(path))
            self._db = Rdict(str(path), options=options,
                             column_families={name: Options() for name in names})
            self._tables = {
                name: self._db.get_column_family(name)
                for name in names
                if name not in ("default", META_CF)
            }
        except Exception as exc:  # rocksdict raises bare Exception on mismatch
            raise MirrorNotFound(f"cannot open mirrored store {path}: {exc}") from exc

    @classmethod
    def for_db(cls, db_path: str | Path) -> "RocksMirrorReader":
        """Open the .rocks sibling of a sqlite path (raises MirrorNotFound if absent)."""
        return cls(mirrored_path_for(db_path))

    def close(self) -> None:
        for cf in self._tables.values():
            cf.close()
        self._tables.clear()
        self._db.close()

    # -- metadata -----------------------------------------------------------

    def _keying_raw(self, table: str) -> Optional[Dict[str, Any]]:
        try:
            meta = self._db.get_column_family(META_CF)
        except Exception:
            return None
        if meta is None:
            return None
        raw = meta.get(f"table:{table}:keying".encode("utf-8"))
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def has_table(self, table: str) -> bool:
        return self._keying_raw(table) is not None

    def table_names(self) -> List[str]:
        return sorted(self._tables.keys())

    # -- rows ----------------------------------------------------------------

    def get_by_rowid(self, table: str, rowid: int) -> Optional[Dict[str, Any]]:
        if table not in self._tables:
            return None
        raw = self._tables[table].get(struct.pack(">Q", rowid))
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    def scan_table(self, table: str) -> Iterator[Tuple[Optional[int], Dict[str, Any]]]:
        """Yield (rowid-or-None, row) in key order."""
        if table not in self._tables:
            return
        for key, value in self._tables[table].items():
            rowid = _decode_rowid(key)
            if rowid is None and key.startswith(b"pk:"):
                pass  # WITHOUT ROWID row: key stays opaque to the caller
            try:
                yield rowid, json.loads(value.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

    def count_rows(self, table: str) -> int:
        if table not in self._tables:
            return 0
        return sum(1 for _ in self._tables[table].keys())

    def find_rows(self, table: str, predicate) -> List[Tuple[Optional[int], Dict[str, Any]]]:
        """In-memory filter over scan_table — the R3 analogue of simple WHEREs."""
        return [pair for pair in self.scan_table(table) if predicate(pair[1])]


def open_mirror_or_none(db_path: str | Path) -> Optional[RocksMirrorReader]:
    """Mirror-or-SQLite helper: returns the reader when a usable mirror sits
    next to the sqlite file, else None (caller uses the sqlite read path)."""
    if not _HAS_ROCKSDB:
        return None
    try:
        return RocksMirrorReader.for_db(db_path)
    except MirrorNotFound:
        return None
