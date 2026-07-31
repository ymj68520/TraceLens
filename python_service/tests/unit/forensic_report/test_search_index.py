from pathlib import Path

from httpserver.services.forensic_report.search_index import SnapshotSearchIndex


def test_search_matches_chinese_phone_path_and_hash(tmp_path: Path):
    index = SnapshotSearchIndex(tmp_path / "search.sqlite3")
    index.add_document(
        kind="record",
        title="短信验证码",
        search_text="验证码 13800138000 /data/mmssms.db abcdef1234",
        record_id="rec_" + "a" * 64,
        evidence_id="e1",
        platform="android",
        category_id="android.sms",
        page=1,
    )

    for query in ("验证码", "13800138000", "/data/mmssms.db", "abcdef1234"):
        total, hits = index.search(query, 0, 10)
        assert total == 1
        assert hits[0].record_id == "rec_" + "a" * 64


def test_search_casefolds_and_pages_deterministically(tmp_path: Path):
    index = SnapshotSearchIndex(tmp_path / "search.sqlite3")
    for number, title in enumerate(("Alpha", "BETA"), start=1):
        index.add_document(
            kind="record",
            title=title,
            search_text=title,
            record_id=f"rec_{number:064x}",
            evidence_id="e1",
            platform="android",
            category_id="android.sms",
            page=number,
        )

    total, hits = index.search("a", 1, 1)
    assert total == 2
    assert [hit.title for hit in hits] == ["BETA"]
    assert index.search("   ", 0, 10) == (0, [])


def test_readonly_open_rejects_empty_or_corrupt_index_without_mutating_it(tmp_path: Path):
    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not sqlite")

    for path in (empty, corrupt):
        before = path.read_bytes()
        try:
            SnapshotSearchIndex.open_readonly(path)
        except Exception:
            pass
        else:  # pragma: no cover - a zero-byte/corrupt SQLite database is invalid
            raise AssertionError("invalid published index was accepted")
        assert path.read_bytes() == before
