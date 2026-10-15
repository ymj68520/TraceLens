"""Tests for httpserver.services.extraction_layout.

Task metadata records ``extracted_files`` while platform analyzers write
``<stem>_extracted_files`` siblings; candidate_roots/resolve_relative_path
bridge that gap.
"""

from __future__ import annotations

from pathlib import Path

from httpserver.services.extraction_layout import (
    candidate_roots,
    resolve_relative_path,
)


def _make_task_dir(tmp_path: Path, extracted: list[str] | None) -> Path:
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()
    recorded = task_dir / "extracted_files"
    if extracted is not None:
        recorded.mkdir()
    return task_dir


def test_recorded_dir_exists_wins(tmp_path: Path) -> None:
    task_dir = _make_task_dir(tmp_path, extracted=[])
    (task_dir / "extracted_files" / "a.txt").write_text("x")
    (task_dir / "linux_extracted_files").mkdir()
    roots = candidate_roots(str(task_dir / "extracted_files"))
    assert roots[0] == task_dir / "extracted_files"
    assert resolve_relative_path(str(task_dir / "extracted_files"), "/a.txt") == str(
        task_dir / "extracted_files" / "a.txt"
    )


def test_missing_recorded_dir_probes_known_stems(tmp_path: Path) -> None:
    task_dir = _make_task_dir(tmp_path, extracted=None)
    linux = task_dir / "linux_extracted_files"
    linux.mkdir()
    (linux / "etc").mkdir()
    (linux / "etc" / "passwd").write_text("root:x:0:0")
    roots = candidate_roots(str(task_dir / "extracted_files"))
    assert roots == [task_dir / "extracted_files", linux]
    assert resolve_relative_path(
        str(task_dir / "extracted_files"), "/etc/passwd"
    ) == str(linux / "etc" / "passwd")


def test_unknown_stems_sort_after_known(tmp_path: Path) -> None:
    task_dir = _make_task_dir(tmp_path, extracted=None)
    (task_dir / "zebra_extracted_files").mkdir()
    (task_dir / "windows_extracted_files").mkdir()
    roots = candidate_roots(str(task_dir / "extracted_files"))
    assert [r.name for r in roots[1:]] == [
        "windows_extracted_files",
        "zebra_extracted_files",
    ]


def test_no_sibling_returns_recorded_only(tmp_path: Path) -> None:
    task_dir = _make_task_dir(tmp_path, extracted=None)
    assert candidate_roots(str(task_dir / "extracted_files")) == [
        task_dir / "extracted_files"
    ]
    assert (
        resolve_relative_path(str(task_dir / "extracted_files"), "/etc/passwd") is None
    )


def test_traversal_rejected(tmp_path: Path) -> None:
    task_dir = _make_task_dir(tmp_path, extracted=[])
    secret = tmp_path / "secret.txt"
    secret.write_text("top")
    assert (
        resolve_relative_path(str(task_dir / "extracted_files"), "/../../secret.txt")
        is None
    )


def test_empty_inputs(tmp_path: Path) -> None:
    assert candidate_roots("") == []
    assert candidate_roots(None) == []
    assert resolve_relative_path("", "/a") is None
    assert resolve_relative_path(str(tmp_path), "") is None
