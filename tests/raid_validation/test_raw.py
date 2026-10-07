# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path
import random

import pytest

from raid.core import RaidError
from raid.raw import RawRaidSession
from raid.export import export_array, verify_package
from .fixtures import make_members, OFFSET


def raw_fixture(root, level=5, layout=2, logical=None):
    originals, expected = make_members(root / "md", level=level, layout=layout, logical=logical)
    target = root / "raw"
    target.mkdir()
    members = []
    # Materialize only generated fixture data regions, not MD metadata.
    for i, original in enumerate(reversed(originals)):
        data = (root / "md" / original["files"][0]).read_bytes()
        length = len(expected) // (3 if level == 0 else 2)
        name = f"opaque-{(i * 17 + 31) % 50}.bin"
        (target / name).write_bytes(data[OFFSET:OFFSET + length])
        members.append({"files": [name]})
    return target, members, expected


@pytest.mark.parametrize("level,layout", [(0, 0), (5, 0), (5, 1), (5, 2), (5, 3)])
def test_metadata_free_reader_and_member_mapping(tmp_path, level, layout):
    root, members, expected = raw_fixture(tmp_path, level, layout)
    random.Random(2).shuffle(members)
    roles = [31, 48, 15]
    order = [next(i for i, member in enumerate(members) if member["files"][0] == f"opaque-{r}.bin") for r in roles]
    plan = {"level": level, "layout": layout, "chunk_size": 4096, "data_offset": 0, "order": order}
    with RawRaidSession(root, members, plan) as session:
        assert session.read_at(0, len(expected)) == expected
        mapping = session.map_range(4000, 17111)
        reconstructed = b""
        for item in mapping:
            data = (root / item["source_file"]).read_bytes()
            reconstructed += data[item["source_offset"]:item["source_offset"] + item["length"]]
        assert reconstructed == expected[4000:21111]
        assert session.manifest()["layout"]["metadata"] is None
        assert session.manifest()["layout"]["array_uuid"] is None
        assert session.manifest()["validation"]["complete_member_set"] is None
        output = tmp_path / "output"
        output.mkdir()
        result = export_array(session, output, max_bytes=1024**2)
        assert verify_package(Path(result["package_directory"]))["status"] == "PASS"


def test_raw_plan_cannot_spoof_or_duplicate_members(tmp_path):
    root, members, _ = raw_fixture(tmp_path)
    bad = {"level": 5, "layout": 2, "chunk_size": 4096, "data_offset": 0, "order": [0, 0, 2]}
    with pytest.raises(RaidError, match="MEMBER_ORDER"):
        RawRaidSession(root, members, bad)
    bad["order"] = [0, 1, 2]
    bad["array_uuid"] = "invented"
    with pytest.raises(RaidError, match="RAW_LAYOUT"):
        RawRaidSession(root, members, bad)


def test_observed_parity_errors_require_explicit_partial_handling(tmp_path):
    root, members, _ = raw_fixture(tmp_path)
    plan = {"level": 5, "layout": 2, "chunk_size": 4096, "data_offset": 0, "order": [0, 1, 2]}
    with (root / members[0]["files"][0]).open("r+b") as out:
        out.write(b"corrupt source")
    with RawRaidSession(root, members, plan) as strict:
        with pytest.raises(RaidError, match="PARITY_MISMATCH"):
            strict.read_at(0, 4096)
    output = tmp_path / "output"
    output.mkdir()
    with RawRaidSession(root, members, plan, parity_mode="observe") as observed:
        result = export_array(observed, output, max_bytes=1024**2)
    assert result["status"] == "PARTIAL"
    assert result["validation"]["parity"]["mismatching_requests"] > 0
    package = Path(result["package_directory"])
    with pytest.raises(RaidError, match="NOT_COMPLETE"):
        verify_package(package)
    assert verify_package(package, allow_partial=True)["business_status"] == "PARTIAL"
