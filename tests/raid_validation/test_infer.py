# SPDX-License-Identifier: AGPL-3.0-or-later
import shutil
import subprocess

import pytest

from raid.infer import infer, enumerate_orders
from raid.core import RaidError
from raid.raw import RawRaidSession
from raid.export import export_array
from raid.results import create_results, read_back
from .test_raw import raw_fixture


def test_csp_never_claims_uniqueness_after_search_limit():
    values, capped = enumerate_orders({i: set(range(5)) for i in range(5)}, cap=2)
    assert len(values) == 2 and capped
    assert all(sorted(order) == list(range(5)) for order in values)
    values, capped = enumerate_orders({0: {2}, 1: {0}, 2: {1}}, cap=2)
    assert values == [[2, 0, 1]] and not capped


def test_no_supported_filesystem_is_explicit_not_guessed(tmp_path):
    root, members, _ = raw_fixture(tmp_path, level=0)
    result = infer(root, list(reversed(members)), timeout=90, max_orders=16)
    assert result["status"] == "NO_SUPPORTED_CANDIDATE"
    assert not result["candidates"]


@pytest.mark.skipif(shutil.which("mkntfs") is None, reason="open-source synthetic formatter unavailable")
def test_ntfs_raw_inference_known_bytes_and_metadata_readback(tmp_path):
    image = tmp_path / "known.ntfs"
    with image.open("wb") as output: output.truncate(16 * 1024**2)
    result = subprocess.run(["mkntfs", "-F", "-Q", "-q", "-s", "512", "-c", "4096", str(image)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    assert result.returncode == 0
    root, members, expected = raw_fixture(tmp_path, level=0, logical=image.read_bytes())
    shuffled = [members[2], members[0], members[1]]
    found = infer(root, shuffled, timeout=120, max_orders=64)
    known_order = [1, 2, 0]
    matching = [c for c in found["candidates"] if c["plan"] == {
        "level": 0, "layout": 0, "chunk_size": 4096, "order": known_order, "data_offset": 0}]
    assert matching, found
    selected = matching[0]
    outputs = tmp_path / "output"
    outputs.mkdir()
    with RawRaidSession(root, shuffled, selected["plan"], inference=selected) as session:
        exported = export_array(session, outputs, max_bytes=32 * 1024**2)
    from pathlib import Path
    package = Path(exported["package_directory"])
    assert (package / "logical.img").read_bytes() == expected
    summary = create_results(root, package, volume_offset=0, max_files=64)
    assert summary["source_type"] == "raid_reassembled_file"
    import sqlite3
    with sqlite3.connect(package / "file-results/results.db") as db:
        row = db.execute("SELECT record_id FROM files WHERE status='READABLE' AND size>0 LIMIT 1").fetchone()
    assert row
    assert read_back(root, package, row[0])["status"] == "MATCH"
    with pytest.raises(RaidError, match="SOURCE_ROOT_OR_TYPE"):
        read_back(tmp_path, package, row[0])
    with sqlite3.connect(package / "file-results/results.db") as db:
        db.execute("UPDATE files SET sha256=? WHERE record_id=?", ("0" * 64, row[0]))
        db.commit()
    with pytest.raises(RaidError, match="DATABASE_OR_SOURCE_BINDING"):
        read_back(root, package, row[0])
