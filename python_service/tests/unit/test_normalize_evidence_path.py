"""Tests for normalize_evidence_path (Evidence identity canonicalization, A1).

Covers the frozen normalization rules AND the explicitly-EXCLUDED behaviors
(no lowercase, no normcase, no dot-segment resolution, no whitespace strip).
"""

import pytest

from httpserver.path_utils import normalize_evidence_path


# --- Frozen rules (must hold) ---

def test_backslash_to_forward_slash():
    assert normalize_evidence_path("\\A\\report.docx") == "/A/report.docx"


def test_collapse_duplicate_separators():
    assert normalize_evidence_path("//A//x") == "/A/x"


def test_strip_trailing_slash():
    assert normalize_evidence_path("/A/x/") == "/A/x"


def test_root_preserved():
    assert normalize_evidence_path("/") == "/"
    assert normalize_evidence_path("//") == "/"
    assert normalize_evidence_path("\\") == "/"


def test_empty_and_none_become_empty_string():
    assert normalize_evidence_path("") == ""
    assert normalize_evidence_path(None) == ""


def test_idempotent_on_already_canonical():
    p = "/documents/report.pdf"
    assert normalize_evidence_path(p) == p
    once = normalize_evidence_path("\\a\\b\\c.txt")
    assert normalize_evidence_path(once) == once


def test_drive_letter_style_kept():
    # Backslash -> slash, but drive letter and case preserved (no normcase).
    assert normalize_evidence_path("D:\\Dir\\File.txt") == "D:/Dir/File.txt"


# --- Explicitly EXCLUDED behaviors (must NOT happen) ---

def test_no_lowercase():
    assert normalize_evidence_path("/Case/File.TXT") == "/Case/File.TXT"


def test_no_dot_segment_resolution():
    assert normalize_evidence_path("/A/../B") == "/A/../B"
    assert normalize_evidence_path("/A/./B") == "/A/./B"


def test_no_whitespace_strip():
    assert normalize_evidence_path(" relative/path ") == " relative/path "


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("\\A\\report.docx", "/A/report.docx"),
        ("//A//report.docx", "/A/report.docx"),
        ("/A/report.docx/", "/A/report.docx"),
        ("/Case/FILE.TxT", "/Case/FILE.TxT"),
        ("/a/../b", "/a/../b"),
    ],
)
def test_normalize_table(raw, expected):
    assert normalize_evidence_path(raw) == expected
