"""Tests for parse_evidence_key / ParsedEvidenceKey (C1).

Covers canonical-key equivalence (C1a), event_type percent-encoding round-trip
(C1b), field-combination validation (C1c), and malformed-input rejection.
"""

from urllib.parse import quote

import pytest
from pydantic import ValidationError

from httpserver.services.evidence import ParsedEvidenceKey, parse_evidence_key


# --- file ---

def test_file_parse_basic():
    p = parse_evidence_key("file:/case/a.txt")
    assert p.evidence_type == "file"
    assert p.normalized_path == "/case/a.txt"
    assert p.canonical_key == "file:/case/a.txt"


def test_C1a_file_canonical_alias_backslash():
    a = parse_evidence_key(r"file:\case\a.txt")
    b = parse_evidence_key("file:/case/a.txt")
    assert a.canonical_key == b.canonical_key == "file:/case/a.txt"


def test_file_canonical_collapses_duplicate_separators_and_trailing_slash():
    p = parse_evidence_key("file://case//a.txt/")
    assert p.canonical_key == "file:/case/a.txt"


# --- cluster ---

def test_cluster_parse_basic():
    p = parse_evidence_key("cluster:v1:100:CREATED")
    assert p.evidence_type == "cluster"
    assert p.version == "v1"
    assert p.unix_minute == 100
    assert p.event_type == "CREATED"
    assert p.canonical_key == "cluster:v1:100:CREATED"


@pytest.mark.parametrize("event_type", ["foo:bar", "微信事件", "FILE-CREATED", "a/b"])
def test_C1b_cluster_roundtrip_special_event_type(event_type):
    key = f"cluster:v1:42:{quote(event_type, safe='')}"
    p = parse_evidence_key(key)
    assert p.event_type == event_type            # decoded back
    assert p.canonical_key == key                 # canonical re-encode is idempotent


def test_cluster_canonical_reparse_identity_stable():
    # key -> parse -> canonical_key -> parse : identity must not drift
    p1 = parse_evidence_key("cluster:v1:7:CREATED")
    p2 = parse_evidence_key(p1.canonical_key)
    assert p2.canonical_key == p1.canonical_key
    assert (p2.unix_minute, p2.event_type, p2.version) == (7, "CREATED", "v1")


# --- malformed inputs ---

@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "unknown:x",
        "file:",
        "file",                 # missing the separator entirely
        "cluster:v1:100",       # only 2 fields after cluster:
        "cluster:v2:100:CREATED",  # unsupported version
        "cluster:v1:notint:CREATED",
        "cluster:v1:100:",      # empty event_type
    ],
)
def test_malformed_key_raises_value_error(bad):
    with pytest.raises(ValueError):
        parse_evidence_key(bad)


# --- C1c: field-combination validation ---

def test_C1c_file_key_rejects_cluster_fields():
    with pytest.raises(ValidationError):
        ParsedEvidenceKey(
            evidence_type="file",
            canonical_key="file:/x",
            normalized_path="/x",
            unix_minute=1,
        )


def test_C1c_cluster_key_rejects_normalized_path():
    with pytest.raises(ValidationError):
        ParsedEvidenceKey(
            evidence_type="cluster",
            canonical_key="cluster:v1:1:CREATED",
            version="v1",
            unix_minute=1,
            event_type="CREATED",
            normalized_path="/x",
        )
