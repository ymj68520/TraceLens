from pathlib import Path
import asyncio
from unittest.mock import patch

from fastapi import HTTPException

from httpserver.services.android_encryption_inspector import AndroidEncryptionInspector
from httpserver.services import android_image_preflight
from httpserver.routes import evidence_intake


def test_encryption_inspector_proof_states():
    check = AndroidEncryptionInspector.inspect
    assert check({"kind": "f2fs", "feature_flags": 1,
                  "encrypted_files": 2, "readable_files": 0})["state"] == "LOCKED"
    assert check({"kind": "f2fs", "feature_flags": 1,
                  "encrypted_files": 2, "readable_files": 3})["state"] == "PARTIALLY_ACCESSIBLE"
    assert check({"kind": "f2fs", "feature_flags": 1,
                  "encrypted_files": 0, "readable_files": 3})["state"] == "FBE_DETECTED"
    assert check({"kind": "ext4", "feature_flags": 0,
                  "encrypted_files": 0, "readable_files": 3})["state"] == "UNENCRYPTED"
    assert check({"kind": "ext4", "feature_flags": None,
                  "encrypted_files": 0, "readable_files": 0})["state"] == "UNKNOWN"
    assert check({"kind": "ext4", "feature_flags": 0,
                  "encrypted_files": 0, "readable_files": 3},
                 metadata_fstab="metadata_encryption=aes-256-xts")["state"] == "METADATA_ENCRYPTION_DETECTED"


def test_image_inspect_rejects_unmarked_volume(tmp_path):
    image = tmp_path / "not-android.img"
    image.write_bytes(b"not an image")
    class Completed:
        returncode = 0
        stderr = b""
        stdout = (b'{"status":"OK","reader":"pinned","volumes":['
                  b'{"base":0,"kind":"ext4","readable":true,"android_markers":[],"feature_flags":0}]}' )
    with patch.object(android_image_preflight.subprocess, "run", return_value=Completed()):
        result = android_image_preflight.inspect(image)
    assert result["inspected"] and not result["ready"]
    assert result["selected_partition"] is None


def test_image_inspect_confirmed_userdata(tmp_path):
    image = tmp_path / "userdata.img"
    image.write_bytes(b"test")
    class Completed:
        returncode = 0
        stderr = b""
        stdout = (b'{"status":"OK","reader":"pinned","volumes":['
                  b'{"base":0,"kind":"f2fs","readable":true,"android_markers":'
                  b'["data/com.android.providers.telephony/databases/mmssms.db"],'
                  b'"feature_flags":0,"readable_files":1,"encrypted_files":0}]}' )
    with patch.object(android_image_preflight.subprocess, "run", return_value=Completed()):
        result = android_image_preflight.inspect(image)
    assert result["ready"]
    assert result["selected_partition"]["encryption"]["state"] == "UNENCRYPTED"


def test_image_inspect_locked_userdata_is_not_ready(tmp_path):
    image = tmp_path / "userdata.img"
    image.write_bytes(b"test")
    class Completed:
        returncode = 0
        stderr = b""
        stdout = (b'{"status":"OK","reader":"pinned","volumes":['
                  b'{"base":0,"kind":"f2fs","readable":true,"android_markers":'
                  b'["data/com.android.providers.telephony/databases/mmssms.db"],'
                  b'"feature_flags":1,"readable_files":0,"encrypted_files":1}]}' )
    with patch.object(android_image_preflight.subprocess, "run", return_value=Completed()):
        result = android_image_preflight.inspect(image)
    assert not result["ready"]
    assert result["reason"] == "ANDROID_USERDATA_LOCKED"
    assert result["selected_partition"]["encryption"]["state"] == "LOCKED"


def test_coverage_manifest_download_requires_existing_task_manifest():
    async def task_record(_):
        return {"id": "task-a"}
    with patch.object(evidence_intake, "get_task_record", task_record), patch.object(
        evidence_intake, "read_coverage", return_value={"manifest": {"schema_version": 1}}
    ):
        response = asyncio.run(evidence_intake.android_coverage_manifest("task-a"))
    assert b'"schema_version": 1' in response.body
    assert response.headers["content-disposition"].endswith('"android-coverage-manifest.json"')
    with patch.object(evidence_intake, "get_task_record", task_record), patch.object(
        evidence_intake, "read_coverage", return_value={"manifest": None}
    ):
        try:
            asyncio.run(evidence_intake.android_coverage_manifest("task-a"))
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("missing manifest was served")


def test_normalization_manifest_download_is_task_scoped():
    async def task_record(_):
        return {"id": "task-super"}
    with patch.object(evidence_intake, "get_task_record", task_record), patch.object(
        evidence_intake, "read_coverage", return_value={"normalization_manifest": {
            "kind": "ANDROID_SPARSE_SUPER", "userdata": {"status": "NOT_PRESENT_IN_SOURCE"}}}
    ):
        response = asyncio.run(evidence_intake.android_normalization_manifest("task-super"))
    assert b"NOT_PRESENT_IN_SOURCE" in response.body
    assert response.headers["content-disposition"].endswith('"android-normalization-manifest.json"')
