"""Unit tests for atomic single-file MarkItDown conversion routes."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import markitdown


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(markitdown.router, prefix="/api/markitdown")
    return TestClient(app)


def _use_raw_text_fallback(monkeypatch):
    locator = MagicMock()
    locator.get_extractor.return_value = None
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)
    return locator


@pytest.fixture(autouse=True)
def _task_workspace(tmp_path, monkeypatch):
    """D2b: every HTTP-level conversion request carries a task anchor.

    The fake task record declares ``tmp_path`` itself as the task workspace
    (the directory holding ``t_files.db``), so the legacy per-test layouts
    under ``tmp_path`` stay inside the task tree.
    """

    class FakeCppBackend:
        async def get_task(self, task_id):
            if task_id == "t1":
                import sqlite3
                database=tmp_path/'t_files.db'
                with sqlite3.connect(database) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,name TEXT,size INTEGER)')
                    for source in tmp_path.rglob('*'):
                        if source.is_file() and not source.name.startswith('t_files.db'):
                            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)',(str(source),source.name,source.stat().st_size))
                return {
                    "id": "t1",
                    "output_files_db": str(tmp_path / "t_files.db"),
                    "extraction_directory":str(tmp_path),
                }
            return None

    class FakeServiceManager:
        cpp_backend = FakeCppBackend()

    monkeypatch.setattr(
        "httpserver.services.get_service_manager",
        lambda: FakeServiceManager(),
    )
    return tmp_path


@pytest.mark.asyncio
async def test_convert_file_to_output_uses_specialized_extractor(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "etc" / "auth.log"
    source.parent.mkdir(parents=True)
    source.write_text("ignored", encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_to_markdown = AsyncMock(return_value="# specialized\n")
    locator = MagicMock()
    locator.get_extractor.return_value = extractor
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "converted"
    assert result.output_path == output_root / "etc" / "auth.log.md"
    assert result.output_path.read_text(encoding="utf-8") == "# specialized\n"
    assert result.output_size == len("# specialized\n".encode("utf-8"))
    extractor.extract_to_markdown.assert_awaited_once_with(str(source))


@pytest.mark.asyncio
async def test_convert_file_to_output_skips_blank_extractor_markdown(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "blank.log"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_to_markdown = AsyncMock(return_value="   \n")
    locator = MagicMock()
    locator.get_extractor.return_value = extractor
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "skipped"
    assert result.output_path is None
    assert not list(output_root.rglob("*.md"))
    assert not list(tmp_path.rglob(".tracelens-textdump-tmp-*"))


@pytest.mark.asyncio
async def test_convert_file_to_output_falls_back_to_raw_utf8_text(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("original text", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "converted"
    assert "original text" in result.output_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_convert_file_to_output_falls_back_to_latin1_text(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_bytes(b"caf\xe9")
    _use_raw_text_fallback(monkeypatch)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "converted"
    assert "café" in result.output_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [b"binary\x00data", b""])
async def test_convert_file_to_output_skips_binary_and_empty_raw_files(
    tmp_path, monkeypatch, contents
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "empty-or-binary.txt"
    source.parent.mkdir()
    source.write_bytes(contents)
    _use_raw_text_fallback(monkeypatch)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "skipped"
    assert result.output_path is None
    assert not list(output_root.rglob("*.md"))


@pytest.mark.asyncio
async def test_convert_file_to_output_isolates_extractor_error_and_cleans_temp(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "broken.log"
    source.parent.mkdir()
    source.write_text("ignored", encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_to_markdown = AsyncMock(side_effect=RuntimeError("extract failed"))
    locator = MagicMock()
    locator.get_extractor.return_value = extractor
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "failed"
    # D1: internal exception text is sanitized to the exception class only.
    assert result.error == "RuntimeError"
    assert "extract failed" not in result.error
    assert not list(tmp_path.rglob(".tracelens-textdump-tmp-*"))


@pytest.mark.asyncio
async def test_convert_file_to_output_isolates_locator_construction_failure(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("notes", encoding="utf-8")
    monkeypatch.setattr(
        markitdown,
        "get_document_extractor_locator",
        MagicMock(side_effect=RuntimeError("locator unavailable")),
    )

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "failed"
    # D1: internal exception text is sanitized to the exception class only.
    assert result.error == "RuntimeError"
    assert "locator unavailable" not in result.error


@pytest.mark.asyncio
async def test_convert_file_to_output_isolates_extractor_selection_failure(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("notes", encoding="utf-8")
    locator = MagicMock()
    locator.get_extractor.side_effect = RuntimeError("selection failed")
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "failed"
    # D1: internal exception text is sanitized to the exception class only.
    assert result.error == "RuntimeError"
    assert "selection failed" not in result.error


@pytest.mark.asyncio
async def test_convert_one_normalizes_empty_failed_outcome_error(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "empty-error.txt"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        markitdown,
        "get_document_extractor_locator",
        MagicMock(side_effect=RuntimeError()),
    )

    outcome = await markitdown._convert_file_to_output(source, input_root, output_root)
    status, detail = await markitdown._convert_one(
        source, input_root, output_root, asyncio.Semaphore(1)
    )

    assert outcome.status == "failed"
    assert outcome.error == "RuntimeError"
    assert status == "failed"
    assert detail == "empty-error.txt: RuntimeError"


def test_write_markdown_atomic_cleans_temp_after_replace_failure(tmp_path, monkeypatch):
    output = tmp_path / "notes.md"
    monkeypatch.setattr(
        markitdown.os,
        "replace",
        MagicMock(side_effect=OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        markitdown._write_markdown_atomic(output, "content")

    assert not output.exists()
    assert not list(tmp_path.glob(".tracelens-textdump-tmp-*"))


def test_convert_one_derives_markdown_output_name(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("case notes", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(output_root),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "status": "converted",
        "input_path": str(source),
        "output_path": str(output_root / "notes.txt.md"),
        "output_size": len((output_root / "notes.txt.md").read_bytes()),
        "error": "",
    }


def test_convert_one_rejects_existing_file_as_output_root(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("notes", encoding="utf-8")
    output_root = tmp_path / "output-file"
    output_root.write_text("not a directory", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    response = _client().post("/api/markitdown/convert-one", json={"task_id": "t1",
        "input_root": str(input_root),
        "input_file": str(source),
        "output_root": str(output_root),
    })

    assert response.status_code == 400
    assert "Output root is not a directory" in response.json()["detail"]


def test_convert_one_returns_failed_outcome_for_locator_construction_failure(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("case notes", encoding="utf-8")
    monkeypatch.setattr(
        markitdown,
        "get_document_extractor_locator",
        MagicMock(side_effect=RuntimeError("locator unavailable")),
    )

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(output_root),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    # D1: internal exception text is sanitized to the exception class only.
    assert response.json()["error"] == "RuntimeError"
    assert "locator unavailable" not in response.json()["error"]


def test_convert_one_rejects_input_outside_root(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    source = tmp_path / "outside.txt"
    input_root.mkdir()
    source.write_text("outside", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(tmp_path / "output"),
        },
    )

    assert response.status_code == 400


def test_convert_one_maps_input_not_a_directory_to_400(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    input_root.mkdir()
    blocker = input_root / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(blocker / "notes.txt"),
            "output_root": str(tmp_path / "output"),
        },
    )

    assert response.status_code == 400
    assert "Invalid input path" in response.json()["detail"]


def test_convert_one_rejects_dangling_output_component_symlink(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "nested" / "notes.txt"
    source.parent.mkdir(parents=True)
    source.write_text("notes", encoding="utf-8")
    output_root.mkdir()
    (output_root / "nested").symlink_to(tmp_path / "missing-target", target_is_directory=True)
    _use_raw_text_fallback(monkeypatch)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(output_root),
        },
    )

    assert response.status_code == 400


@pytest.mark.parametrize("case", ["input_file", "input_root", "output_root", "output_component", "output_file"])
def test_convert_one_rejects_symlinked_paths(tmp_path, monkeypatch, case):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "nested" / "notes.txt"
    source.parent.mkdir(parents=True)
    source.write_text("notes", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    request_input_root = input_root
    request_input_file = source
    request_output_root = output_root
    if case == "input_file":
        request_input_file = input_root / "linked-notes.txt"
        request_input_file.symlink_to(source)
    elif case == "input_root":
        request_input_root = tmp_path / "linked-input"
        request_input_root.symlink_to(input_root, target_is_directory=True)
    elif case == "output_root":
        output_root.mkdir()
        request_output_root = tmp_path / "linked-output"
        request_output_root.symlink_to(output_root, target_is_directory=True)
    elif case == "output_component":
        target = tmp_path / "output-target"
        target.mkdir()
        output_root.mkdir()
        (output_root / "nested").symlink_to(target, target_is_directory=True)
    elif case == "output_file":
        output_root.mkdir()
        (output_root / "nested").mkdir()
        target = tmp_path / "unrelated.md"
        target.write_text("do not replace", encoding="utf-8")
        (output_root / "nested" / "notes.txt.md").symlink_to(target)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(request_input_root),
            "input_file": str(request_input_file),
            "output_root": str(request_output_root),
        },
    )

    assert response.status_code == 400


def test_convert_one_normalizes_empty_output_write_oserror(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("case notes", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    def fail_write(output_path, markdown):
        raise OSError()

    monkeypatch.setattr(markitdown, "_write_markdown_atomic", fail_write)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(tmp_path / "output"),
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Output write failed: OSError"


def test_convert_one_reports_atomic_write_oserror_as_server_error(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("case notes", encoding="utf-8")
    _use_raw_text_fallback(monkeypatch)

    def fail_write(output_path, markdown):
        raise OSError("disk full")

    monkeypatch.setattr(markitdown, "_write_markdown_atomic", fail_write)

    response = _client().post(
        "/api/markitdown/convert-one",
        json={"task_id": "t1",
            "input_root": str(input_root),
            "input_file": str(source),
            "output_root": str(tmp_path / "output"),
        },
    )

    assert response.status_code == 500
    # D1: internal exception text is sanitized to the exception class only.
    assert response.json()["detail"] == "Output write failed: OSError"
    assert "disk full" not in response.json()["detail"]


def test_batch_convert_normalizes_empty_output_directory_setup_oserror(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()

    real_mkdir = Path.mkdir

    def fail_output_mkdir(self, *args, **kwargs):
        if self == output_root:
            raise OSError()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_output_mkdir)

    response = _client().post(
        "/api/markitdown/batch-convert",
        json={"task_id": "t1","input_dir": str(input_root), "output_dir": str(output_root)},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        f"Cannot create output directory {output_root}: OSError"
    )


@pytest.mark.asyncio
async def test_batch_wrapper_normalizes_empty_oserror(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "notes.txt"
    source.parent.mkdir()
    source.write_text("notes", encoding="utf-8")

    async def fail_conversion(file_path, received_input_root, received_output_root):
        raise OSError()

    monkeypatch.setattr(markitdown, "_convert_file_to_output", fail_conversion)

    status, detail = await markitdown._convert_one(
        source, input_root, output_root, asyncio.Semaphore(1)
    )

    assert status == "failed"
    assert detail == "notes.txt: OSError"


@pytest.mark.concurrency
def test_batch_convert_uses_shared_primitive_with_bounded_concurrency_and_error_cap(
    tmp_path, monkeypatch
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    (input_root / "converted.txt").write_text("converted", encoding="utf-8")
    (input_root / "skipped.txt").write_text("skipped", encoding="utf-8")
    for index in range(51):
        (input_root / f"failed-{index}.txt").write_text("failed", encoding="utf-8")

    calls = []
    active = 0
    max_active = 0

    async def fake_convert(file_path, received_input_root, received_output_root):
        nonlocal active, max_active
        calls.append((file_path, received_input_root, received_output_root))
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        if file_path.name == "converted.txt":
            return markitdown.FileConversionOutcome(
                "converted", file_path, output_root / "converted.txt.md", 10
            )
        if file_path.name == "skipped.txt":
            return markitdown.FileConversionOutcome("skipped", file_path)
        return markitdown.FileConversionOutcome(
            "failed", file_path, error=f"cannot convert {file_path.name}"
        )

    monkeypatch.setattr(markitdown, "_convert_file_to_output", fake_convert)

    response = _client().post(
        "/api/markitdown/batch-convert",
        json={"task_id": "t1","input_dir": str(input_root), "output_dir": str(output_root)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 53
    assert body["converted"] == 1
    assert body["skipped"] == 1
    assert body["failed"] == 51
    assert len(body["errors"]) == 51
    assert all(
        error.startswith("failed-") and ": cannot convert failed-" in error
        for error in body["errors"][:-1]
    )
    assert body["errors"][-1] == "... and 1 more failures"
    assert len(calls) == 53
    assert all(call[1:] == (input_root, output_root) for call in calls)
    assert max_active == 4


# ---------------------------------------------------------------------------
# /convert extractor dispatch
#
# The C++ backend sends forensic artifacts (.pf/.evtx/hives) to /convert, not
# only documents. That endpoint used to call markitdown unconditionally, so
# every prefetch file, event log and registry hive came back as HTTP 500
# "conversion failed" — markitdown raises UnsupportedFormatException for them.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_uses_specialized_extractor_for_forensic_artifact(
    tmp_path, monkeypatch
):
    prefetch = tmp_path / "CMD.EXE-DEADBEEF.pf"
    prefetch.write_bytes(b"MAM\x04" + b"\x00" * 64)

    class FakeExtractor:
        async def extract_to_markdown(self, file_path):
            return "# Prefetch Analysis\n**Run Count:** 3\n"

    locator = MagicMock()
    locator.get_extractor.return_value = FakeExtractor()
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    markitdown._md_instance = None
    monkeypatch.setattr(
        markitdown, "_get_markitdown", lambda: pytest.fail("markitdown must not run")
    )

    response = _client().post(
        "/api/markitdown/convert",
        json={"task_id": "t1", "file_path": str(prefetch)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "Run Count" in body["content"]


@pytest.mark.asyncio
async def test_convert_falls_back_to_markitdown_for_documents(tmp_path, monkeypatch):
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF-1.4\n")

    locator = MagicMock()
    locator.get_extractor.side_effect = AssertionError(
        "markitdown-native formats must not hit the extractor registry"
    )
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    class FakeMd:
        def convert(self, file_path):
            return MagicMock(markdown="# Converted PDF", title="report")

    monkeypatch.setattr(markitdown, "_get_markitdown", lambda: FakeMd())

    response = _client().post(
        "/api/markitdown/convert",
        json={"task_id": "t1", "file_path": str(document)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "# Converted PDF"
    assert body["title"] == "report"


@pytest.mark.asyncio
async def test_convert_does_not_turn_corrupt_artifact_into_fallback_content(
    tmp_path, monkeypatch
):
    artifact = tmp_path / "weird.evtx"
    artifact.write_bytes(b"ElfFile\x00" + b"\x00" * 32)

    class BrokenExtractor:
        async def extract_to_markdown(self, file_path):
            raise RuntimeError("corrupt log")

    locator = MagicMock()
    locator.get_extractor.return_value = BrokenExtractor()
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    class FakeMd:
        def convert(self, file_path):
            raise AssertionError("a corrupt forensic artifact must not reach a generic converter")

    monkeypatch.setattr(markitdown, "_get_markitdown", lambda: FakeMd())

    response = _client().post(
        "/api/markitdown/convert",
        json={"task_id": "t1", "file_path": str(artifact)},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DOCUMENT_PARSE_FAILED"
    assert "content" not in response.json()


# ---------------------------------------------------------------------------
# ExtractorLocator filename routing
#
# Registry hives (SAM, SYSTEM, SOFTWARE, SECURITY, DEFAULT, NTUSER.DAT) and the
# Linux login records (wtmp/btmp) have no extension. The locator used to bail
# out of the empty-extension branch before consulting the filename map, so all
# of them were reported as unsupported and every hive in a case failed.
# ---------------------------------------------------------------------------


def test_locator_routes_extensionless_registry_hive_by_filename(tmp_path):
    from httpserver.services.document_extractor import get_document_extractor_locator

    hive = tmp_path / "SAM"
    hive.write_bytes(b"regf" + b"\x00" * 60)

    extractor = get_document_extractor_locator().get_extractor(str(hive))

    assert extractor is not None
    assert type(extractor).__name__ == "RegistryExtractor"


def test_locator_still_rejects_unknown_extensionless_binary(tmp_path):
    from httpserver.services.document_extractor import get_document_extractor_locator

    blob = tmp_path / "randomblob"
    blob.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07")

    assert get_document_extractor_locator().get_extractor(str(blob)) is None


def test_locator_routes_extensionless_plain_text_by_content(tmp_path):
    from httpserver.services.document_extractor import get_document_extractor_locator

    note = tmp_path / "notes"
    note.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")

    extractor = get_document_extractor_locator().get_extractor(str(note))

    assert extractor is not None
    assert type(extractor).__name__ == "TextDumpExtractor"
