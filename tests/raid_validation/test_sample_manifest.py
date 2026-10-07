# SPDX-License-Identifier: AGPL-3.0-or-later
import importlib.util
import json
from pathlib import Path

import pytest

from raid.core import RaidError
from .fixtures import make_members


def tool():
    path = Path(__file__).resolve().parents[2] / "scripts" / "raid_sample_manifest.py"
    spec = importlib.util.spec_from_file_location("raid_sample_manifest", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_manifest_does_not_turn_inventory_into_acceptance(tmp_path):
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    (source / "no-metadata.img").write_bytes(b"\0" * 8192)
    outside = tmp_path / "private.img"
    outside.write_bytes(b"not evidence")
    (source / "escape.img").symlink_to(outside)
    output = tmp_path / "output"
    output.mkdir()
    result = tool().inventory(source, output, full_hash=True)
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["status"] == "INVENTORIED_NOT_ACCEPTED"
    assert manifest["summary"]["image_count"] == 4
    assert manifest["summary"]["md_metadata_candidates"] == 3
    assert manifest["summary"]["source_unchanged"]
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert all(group["reassembly_validation"] == "NOT_RUN" for group in manifest["groups"])
    assert "CURRENT_MD_ADAPTER_DOES_NOT_COVER_ALL_SAMPLES" in manifest["warnings"]
    assert not any(item["source_file"] == "escape.img" for item in manifest["files"])


def test_manifest_rejects_output_within_evidence(tmp_path):
    source = tmp_path / "inbox"
    make_members(source)
    with pytest.raises(RaidError, match="EVIDENCE_DISJOINT"):
        tool().inventory(source, source, full_hash=True)


def test_manifest_rejects_inventory_over_limit(tmp_path, monkeypatch):
    source = tmp_path / "inbox"
    source.mkdir()
    for name in ("a.img", "b.img"):
        (source / name).write_bytes(b"fixture")
    module = tool()
    monkeypatch.setattr(module, "MAX_FILES", 1)
    with pytest.raises(RaidError, match="INVENTORY_FILE_LIMIT"):
        module.paths_within(source)


def test_manifest_rechecks_earlier_sources_before_commit(tmp_path, monkeypatch):
    source = tmp_path / "inbox"
    source.mkdir()
    (source / "a.img").write_bytes(b"a" * 8192)
    (source / "b.img").write_bytes(b"b" * 8192)
    output = tmp_path / "output"
    output.mkdir()
    module = tool()
    original_hash = module.hash_handle
    calls = 0
    def changed_while_reading_later_file(handle, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (source / "a.img").write_bytes(b"changed during a later read")
        return original_hash(handle, **kwargs)
    monkeypatch.setattr(module, "hash_handle", changed_while_reading_later_file)
    with pytest.raises(RaidError, match="SOURCE_CHANGED_BEFORE_INVENTORY_COMMIT"):
        module.inventory(source, output, full_hash=True)
    assert not list(output.glob("*/sample_manifest.json"))
