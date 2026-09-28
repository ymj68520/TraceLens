"""Only synthetic sample manifests; no machine-wide sample scan."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from android_field_sample_manifest import validate


def test_explicit_segment_and_attachment_hashes_and_authorization(tmp_path):
    sample = tmp_path / "synthetic.img"
    segment = tmp_path / "synthetic.E02"
    attachment = tmp_path / "synthetic-attachment.bin"
    for path in (sample, segment, attachment):
        path.write_bytes(path.name.encode())
    item = lambda path: {"local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"sample_id": "SYNTHETIC", "source_category": "original_android",
                "files": [{**item(sample), "segments": [item(segment)]}],
                "attachments": [item(attachment)], "extraction_tool": {"name": None, "version": None},
                "container": "RAW", "filesystem": "EXT4", "readability": "READABLE",
                "target_artifacts": ["sms", "contacts", "apps", "wifi"],
                "expected_records": {}, "comparison_source": None,
                "authorization_record": "synthetic-only-test", "validation_status": "AUTHORIZED_SYNTHETIC"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate(path, full_hash=True)
    assert result["ready_for_analysis"] is True
    assert len(result["files"]) == 3 and all(row["status"] == "MATCH" for row in result["files"])
    manifest["authorization_record"] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="authorization"):
        validate(path, full_hash=True)
    manifest["authorization_record"] = "synthetic-only-test"
    manifest["readability"] = "LOCKED"
    manifest["business_goal"] = {"required_messages_readable": True}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate(path, full_hash=True)["real_sample_acceptance"] == "UNMET_LOCKED"
    manifest["target_artifacts"].append("wechat")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="sample-driven"):
        validate(path, full_hash=True)
