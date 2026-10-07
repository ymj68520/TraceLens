# SPDX-License-Identifier: AGPL-3.0-or-later
import concurrent.futures
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from raid.core import RaidError, RaidSession, MAX_REQUEST, confined_open
from raid.export import export_array, verify_package
from .fixtures import CHUNK, OFFSET, checksum, edit_metadata, make_members


@pytest.mark.parametrize("level", [0, 1, 5])
def test_unordered_members_match_independent_logical_bytes(tmp_path, level):
    source = tmp_path / "inbox"
    members, expected = make_members(source, level)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    for permutation in itertools.permutations(members):
        with RaidSession(source, list(permutation)) as session:
            assert session.size == len(expected)
            for offset, length in [(0, len(expected)), (1, 17111), (CHUNK - 17, 120011),
                                   (65530, 131100), (len(expected) - 101, 101)]:
                assert session.read_at(offset, length) == expected[offset:offset + length]
            assert [m["role"] for m in session.manifest()["layout"]["members"]] == [0, 1, 2]
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


@pytest.mark.parametrize("layout", range(6))
def test_raid5_all_supported_layouts(tmp_path, layout):
    source = tmp_path / "inbox"
    members, expected = make_members(source, layout=layout)
    with RaidSession(source, members) as session:
        assert session.read_at(0, len(expected)) == expected


def test_parallel_reads_are_seek_safe(tmp_path):
    source = tmp_path / "inbox"
    members, expected = make_members(source)
    with RaidSession(source, members) as session:
        ranges = [(i * 1009, 11001) for i in range(100)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(lambda pair: session.read_at(*pair), ranges))
        assert result == [expected[offset:offset + count] for offset, count in ranges]


@pytest.mark.parametrize("offset,length", [(-1, 1), (0, -1), (0, MAX_REQUEST + 1), (True, 1), (0, True)])
def test_invalid_reads(tmp_path, offset, length):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    with RaidSession(source, members) as session:
        with pytest.raises(RaidError, match="LOGICAL_READ_OUT_OF_RANGE"):
            session.read_at(offset, length)


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "a/../../outside", "a\\..\\outside", "a//b", "./a", ""])
def test_path_traversal_rejected(tmp_path, path):
    with pytest.raises(RaidError, match="INVALID_MEMBER_PATH"):
        confined_open(tmp_path, path)


def test_symlink_and_directory_symlink_escape(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (tmp_path / "secret").write_text("not evidence")
    (inbox / "link").symlink_to(tmp_path / "secret")
    (inbox / "dir").symlink_to(tmp_path, target_is_directory=True)
    for path in ["link", "dir/secret"]:
        with pytest.raises(RaidError, match="SYMLINK"):
            confined_open(inbox, path)


def test_missing_and_duplicate_members(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    with pytest.raises(RaidError, match="INCOMPLETE"):
        RaidSession(source, members[:2])
    with pytest.raises(RaidError, match="DUPLICATE_SOURCE"):
        RaidSession(source, [members[0], members[0], members[1]])


@pytest.mark.parametrize("offset,fmt,value,code", [
    (200, "<Q", 8, "MD_METADATA_CONFLICT"),
    (256, "<H", 1, "MD_METADATA_CONFLICT"),
    (8, "<I", 4, "MD_FEATURE_NOT_VALIDATED"),
    (208, "<Q", 0, "MD_NOT_CLEAN"),
    (220, "<I", 1000000, "MD_ROLE_TABLE_LIMIT"),
    (160, "<I", 64, "MD_ROLE_TABLE_LIMIT"),
    (144, "<Q", 9, "MD_SUPER_OFFSET_MISMATCH"),
    (136, "<Q", 1000000, "TRUNCATED_MEMBER_DATA"),
])
def test_bad_metadata_fails_closed(tmp_path, offset, fmt, value, code):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    edit_metadata(source / members[0]["files"][0], offset, fmt, value)
    with pytest.raises(RaidError, match=code):
        RaidSession(source, members)


def test_metadata_checksum_required(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    edit_metadata(source / members[0]["files"][0], 200, "<Q", 8, repair_checksum=False)
    with pytest.raises(RaidError, match="CHECKSUM"):
        RaidSession(source, members)


def test_unvalidated_metadata_location_is_not_admitted(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source, metadata_sector=0)
    with pytest.raises(RaidError, match="MD_V1_METADATA_LOCATION_NOT_VALIDATED"):
        RaidSession(source, members)


@pytest.mark.parametrize("level,code", [(1, "MIRROR_CONFLICT"), (5, "PARITY_MISMATCH")])
def test_content_conflict_not_published(tmp_path, level, code):
    source = tmp_path / "inbox"
    members, _ = make_members(source, level)
    path = source / members[0]["files"][0]
    with path.open("r+b") as image:
        image.seek(OFFSET + 12)
        image.write(b"bad")
    output = tmp_path / "output"
    output.mkdir()
    with RaidSession(source, members) as session:
        with pytest.raises(RaidError, match=code):
            export_array(session, output, max_bytes=1024**2)
    package = next(output.iterdir())
    assert not (package / "logical.img").exists()
    assert not (package / "raid_manifest.json").exists()
    assert json.loads((package / "failure.json").read_text())["status"] == "FAILED"


def test_held_source_changes_and_replacement_rejected(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    with RaidSession(source, members) as session:
        path = source / members[0]["files"][0]
        clone = path.with_name("replacement")
        clone.write_bytes(path.read_bytes())
        clone.replace(path)
        with pytest.raises(RaidError, match="SOURCE_CHANGED"):
            session.read_at(0, 512)


def test_export_hashes_and_offline_verification(tmp_path):
    source = tmp_path / "inbox"
    members, expected = make_members(source)
    output = tmp_path / "output"
    output.mkdir()
    with RaidSession(source, members) as session:
        result = export_array(session, output, max_bytes=1024**2)
    package = Path(result["package_directory"])
    assert result["derived_image"]["sha256"] == hashlib.sha256(expected).hexdigest()
    assert (package / "logical.img").read_bytes() == expected
    assert result["source_sha256"] == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    assert verify_package(package)["status"] == "PASS"
    with (package / "logical.img").open("r+b") as image:
        image.write(b"changed")
    with pytest.raises(RaidError, match="PACKAGE_IMAGE_CHANGED"):
        verify_package(package)


def test_size_limit_disjoint_output_and_cancel(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    output = tmp_path / "output"
    output.mkdir()
    with RaidSession(source, members) as session:
        with pytest.raises(RaidError, match="SIZE_LIMIT"):
            export_array(session, output, max_bytes=100)
        with pytest.raises(RaidError, match="DISJOINT"):
            export_array(session, source, max_bytes=1024**2)
        with pytest.raises(RaidError, match="CANCELLED"):
            export_array(session, output, max_bytes=1024**2, cancelled=lambda: True)
    assert not list(output.glob("*/logical.img"))
    assert not list(output.glob("*/raid_manifest.json"))


def test_timeout_retains_partial_not_completed(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    output = tmp_path / "output"
    output.mkdir()
    with RaidSession(source, members) as session:
        with pytest.raises(RaidError, match="EXPORT_TIMEOUT"):
            export_array(session, output, max_bytes=1024**2, timeout=0.000001)
    assert not list(output.glob("*/raid_manifest.json"))


def test_cli_is_real_entrypoint(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": 1, "members": members}))
    cli = Path(__file__).resolve().parents[2] / "scripts" / "raid_cli.py"
    result = subprocess.run([sys.executable, str(cli), "inspect", "--inbox", str(source),
                             "--selection", str(selection)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "READY_READONLY"
    assert "NOT_CALCULATED" in result.stdout


def test_cli_rejects_invalid_worker_limits(tmp_path):
    cli = Path(__file__).resolve().parents[2] / "scripts" / "raid_cli.py"
    result = subprocess.run([sys.executable, str(cli), "inspect", "--max-memory-mib", "1"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "INVALID_WORKER_RESOURCE_LIMIT"
