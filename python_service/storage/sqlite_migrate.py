"""SQLite → RocksDB migration (mvp-phase1-acceptance SPEC §8, R1/R6 groundwork).

Generic one-shot importer: every SQLite table becomes a column family of the
same name; each row is stored under an ordered key (big-endian rowid, or a
``pk:`` JSON key for WITHOUT ROWID tables) with the full row as a JSON value.
Schema metadata (original DDL, column list, row count, keying mode) lands in
the ``_meta`` family so readers can reconstruct table semantics without the
SQLite file.

The import is read-only on the source database and non-destructive on the
target (an existing RocksDB dir is only ever added to; pass a fresh path for
a clean migration).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from storage.rocksdb_store import META_CF, RocksDBStore, encode_rowid
except ImportError:  # direct script execution: repo-root/scripts layout
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_service"))
    from storage.rocksdb_store import META_CF, RocksDBStore, encode_rowid  # type: ignore

_BLOB_KEY = "__blob_b64__"


def _jsonify(value: Any) -> Any:
    if isinstance(value, bytes):
        return {_BLOB_KEY: base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    return value


def encode_value(cell: Any) -> bytes:
    return json.dumps(_jsonify(cell), sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_value(raw: bytes) -> List[Tuple[str, Any]]:
    """Inverse of encode_value for one row: returns column→value pairs."""
    row = json.loads(raw.decode("utf-8"))
    out = []
    for name, value in row.items():
        if isinstance(value, dict) and _BLOB_KEY in value:
            value = base64.b64decode(value[_BLOB_KEY])
        out.append((name, value))
    return out


def _tables(conn: sqlite3.Connection, only: Optional[List[str]]) -> List[Tuple[str, str]]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    tables = [(name, sql or "") for name, sql in rows]
    if only:
        wanted = set(only)
        tables = [(name, sql) for name, sql in tables if name in wanted]
    return tables


def _rowid_keyed(conn: sqlite3.Connection, table: str) -> bool:
    """False for WITHOUT ROWID tables."""
    try:
        conn.execute(f'SELECT rowid FROM "{table}" LIMIT 1')
        return True
    except sqlite3.Error:
        return False


def _primary_key(conn: sqlite3.Connection, table: str) -> List[str]:
    return [
        row[1]
        for row in conn.execute(f'PRAGMA table_info("{table}")')
        if row[5] > 0  # pk column order
    ]


def migrate(
    sqlite_path: str | Path,
    rocks_path: str | Path,
    tables: Optional[List[str]] = None,
    batch_size: int = 2000,
) -> Dict[str, int]:
    """Import every table of ``sqlite_path`` into a RocksDB store.

    Returns {table_name: migrated_row_count}.
    """
    conn = sqlite3.connect(f"file:{Path(sqlite_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        chosen = _tables(conn, tables)
        store = RocksDBStore(rocks_path, column_families=[name for name, _ in chosen])
        try:
            counts: Dict[str, int] = {}
            for name, ddl in chosen:
                counts[name] = _migrate_table(conn, store, name, ddl, batch_size)
            store.set_meta("source_sqlite", str(Path(sqlite_path).resolve()))
            store.flush()
            return counts
        finally:
            store.close()
    finally:
        conn.close()


def _migrate_table(
    conn: sqlite3.Connection,
    store: RocksDBStore,
    table: str,
    ddl: str,
    batch_size: int,
) -> int:
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    rowid_keyed = _rowid_keyed(conn, table)
    pk = _primary_key(conn, table)

    select = f'SELECT rowid, * FROM "{table}"' if rowid_keyed else f'SELECT * FROM "{table}"'
    count = 0
    batch = []
    for row in conn.execute(select):
        if rowid_keyed:
            key = encode_rowid(row[0])
            cells = {col: row[col] for col in columns}
        else:
            pk_values = [row[col] for col in pk]
            if any(v is None for v in pk_values):
                raise ValueError(f"NULL in primary key of {table}; cannot migrate")
            key = b"pk:" + encode_value(dict(zip(pk, pk_values)))
            cells = {col: row[col] for col in columns}
        batch.append((table, key, encode_value(cells)))
        count += 1
        if len(batch) >= batch_size:
            store.batch(batch)
            batch = []
    if batch:
        store.batch(batch)

    store.batch([
        (META_CF, f"table:{table}:ddl".encode("utf-8"), ddl.encode("utf-8")),
        (META_CF, f"table:{table}:columns".encode("utf-8"), encode_value(columns)),
        (
            META_CF,
            f"table:{table}:keying".encode("utf-8"),
            encode_value({"rowid_keyed": rowid_keyed, "pk": pk, "count": count}),
        ),
    ])
    return count


def verify(sqlite_path: str | Path, rocks_path: str | Path) -> Dict[str, bool]:
    """Per-table parity check: row counts and full-content digests must match."""
    conn = sqlite3.connect(f"file:{Path(sqlite_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # column_families=None discovers every family present in the store.
    store = RocksDBStore(rocks_path)
    results: Dict[str, bool] = {}
    try:
        tables = []
        for name, _ in store.scan_prefix(META_CF, b"table:"):
            key = name.decode("utf-8")
            if key.endswith(":keying"):
                tables.append(key[len("table:") : -len(":keying")])
        for table in sorted(set(tables)):
            raw = store.get(META_CF, f"table:{table}:keying".encode("utf-8"))
            keying = json.loads(raw.decode("utf-8"))
            sql_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

            digest = hashlib.sha256()
            kv_count = 0
            for key, value in store.scan_prefix(table, b""):
                kv_count += 1
                digest.update(key)
                digest.update(value)
            results[table] = kv_count == keying["count"] == sql_count
            # content digest compared against the source, ordered by key
            if rowid_keyed := keying["rowid_keyed"]:
                source = conn.execute(
                    f'SELECT rowid, * FROM "{table}" ORDER BY rowid'
                )
            else:
                source = conn.execute(f'SELECT * FROM "{table}"')
            src_digest = hashlib.sha256()
            src_count = 0
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            for row in source:
                src_count += 1
                if rowid_keyed:
                    key = encode_rowid(row[0])
                    cells = {col: row[col] for col in columns}
                else:
                    pk = keying["pk"]
                    cells = {col: row[col] for col in columns}
                    key = b"pk:" + encode_value({col: row[col] for col in pk})
                src_digest.update(key)
                src_digest.update(encode_value(cells))
            results[table] = results[table] and digest.hexdigest() == src_digest.hexdigest()
            _ = src_count
    finally:
        store.close()
        conn.close()
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate a SQLite database into RocksDB")
    parser.add_argument("sqlite_path")
    parser.add_argument(
        "--out",
        help="RocksDB directory (default: <sqlite path with .db suffix replaced by .rocks>)",
    )
    parser.add_argument("--tables", nargs="*", help="Subset of tables to migrate")
    parser.add_argument("--verify", action="store_true", help="Run the parity check after migrating")
    args = parser.parse_args(argv)

    out = args.out or str(Path(args.sqlite_path).with_suffix(".rocks"))
    counts = migrate(args.sqlite_path, out, tables=args.tables)
    for table, count in sorted(counts.items()):
        print(f"{table}: {count} rows -> {out}/{table}")
    if args.verify:
        results = verify(args.sqlite_path, out)
        ok = all(results.values())
        for table, passed in sorted(results.items()):
            print(f"verify {table}: {'OK' if passed else 'MISMATCH'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
