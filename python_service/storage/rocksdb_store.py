"""RocksDB storage foundation (mvp-phase1-acceptance SPEC §8, R1).

Thin, explicit wrapper over ``rocksdict`` (RocksDB bindings) that the later
migration phases (R4/R5) build on. Design constraints:

- bytes in / bytes out: key and value codecs live with the callers, so the
  store never guesses a serialization.
- fixed set of column families declared up front (one per migrated SQLite
  table, plus a ``_meta`` bookkeeping family).
- ordered keys: callers use big-endian fixed-width encodings (see
  ``encode_rowid``) so prefix scans read like ordered table scans.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    from rocksdict import Options, Rdict, WriteBatch
    _HAS_ROCKSDB = True
except ImportError:  # pragma: no cover - exercised only on bare envs
    _HAS_ROCKSDB = False

META_CF = "_meta"


def available() -> bool:
    """True when the rocksdict backend is importable."""
    return _HAS_ROCKSDB


class RocksDBUnavailable(RuntimeError):
    """Raised when the store is used without the rocksdict dependency."""


def encode_rowid(rowid: int) -> bytes:
    """Big-endian 8-byte rowid key: lexicographic order == numeric order."""
    if rowid < 0:
        raise ValueError("rowid must be non-negative")
    return struct.pack(">Q", rowid)


def decode_rowid(key: bytes) -> int:
    return struct.unpack(">Q", key)[0]


def ensure_parent(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class RocksDBStore:
    """Column-family oriented RocksDB handle.

    Column families are declared at open time and created on demand; the
    default column family stays empty by convention (RocksDB requires one)
    while all data lives in named families.
    """

    def __init__(self, path: str | Path, column_families: Optional[Iterable[str]] = None):
        """
        ``column_families`` semantics:
        - a list: open exactly these families (creating any that are missing);
        - ``None`` (default): discover and open every family already in the
          store — the read path for migrated databases.
        """
        if not _HAS_ROCKSDB:
            raise RocksDBUnavailable(
                "rocksdict is not installed; pip install rocksdict"
            )
        self.path = ensure_parent(path)
        if column_families is None:
            try:
                discovered = [cf for cf in Rdict.list_cf(str(self.path)) if cf != "default"]
            except Exception:
                discovered = []
            self._names = discovered or [META_CF]
        else:
            self._names = [META_CF, *[cf for cf in column_families if cf != META_CF]]
        options = Options()
        options.create_if_missing(True)
        options.create_missing_column_families(True)
        # Declaring the families at open lets RocksDB create any missing ones;
        # reopening an existing store with the same list reattaches to them.
        self._db: Rdict = Rdict(
            str(self.path),
            options=options,
            column_families={name: Options() for name in self._names},
        )
        self._cfs: dict[str, Rdict] = {
            name: self._db.get_column_family(name) for name in self._names
        }

    # -- single-key ops ----------------------------------------------------
    def put(self, cf: str, key: bytes, value: bytes) -> None:
        self._cf(cf)[key] = value

    def get(self, cf: str, key: bytes) -> Optional[bytes]:
        return self._cf(cf).get(key)

    def delete(self, cf: str, key: bytes) -> None:
        del self._cf(cf)[key]

    # -- batch --------------------------------------------------------------
    def batch(self, ops: Iterable[tuple[str, bytes, Optional[bytes]]]) -> None:
        """Atomic multi-put/delete: (cf, key, value-or-None) tuples."""
        wb = WriteBatch()
        for cf_name, key, value in ops:
            handle = self._db.get_column_family_handle(cf_name)
            if value is None:
                wb.delete(key, column_family=handle)
            else:
                wb.put(key, value, column_family=handle)
        self._db.write(wb)

    # -- scans ---------------------------------------------------------------
    def scan_prefix(self, cf: str, prefix: bytes) -> Iterator[tuple[bytes, bytes]]:
        """Yield (key, value) pairs whose key starts with ``prefix``, ordered."""
        col = self._cf(cf)
        it = col.iter()
        it.seek(prefix)
        while it.valid():
            key = it.key()
            if not key.startswith(prefix):
                break
            yield key, it.value()
            it.next()

    def count_prefix(self, cf: str, prefix: bytes) -> int:
        return sum(1 for _ in self.scan_prefix(cf, prefix))

    # -- meta bookkeeping ----------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self.put(META_CF, key.encode("utf-8"), value.encode("utf-8"))

    def get_meta(self, key: str) -> Optional[str]:
        raw = self.get(META_CF, key.encode("utf-8"))
        return raw.decode("utf-8") if raw is not None else None

    # -- lifecycle -------------------------------------------------------------
    def column_families(self) -> list[str]:
        return list(self._names)

    def flush(self) -> None:
        for col in self._cfs.values():
            col.flush()

    def close(self) -> None:
        for col in self._cfs.values():
            col.close()
        self._cfs.clear()
        self._db.close()

    def destroy(self) -> None:
        """Close and remove the whole database directory."""
        self.close()
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "RocksDBStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- internals ---------------------------------------------------------------
    def _cf(self, name: str) -> Rdict:
        try:
            return self._cfs[name]
        except KeyError as exc:
            raise KeyError(f"unknown column family: {name}") from exc
