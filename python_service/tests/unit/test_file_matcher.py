# python_service/httpserver/tests/unit/test_file_matcher.py
"""
Unit tests for FileMatcher.
"""

import time
import pytest

from httpserver.services.case_analysis.file_matcher import (
    FileMatcher,
    MatchResult,
)


@pytest.fixture
def sample_batch_files():
    """Sample batch files including duplicates."""
    now = int(time.time())
    day_ago = now - 86400
    week_ago = now - 604800

    return [
        {
            "path": "/home/user/documents/document.pdf",
            "name": "document.pdf",
            "size": 1024000,
            "mtime": now,
        },
        {
            "path": "/tmp/document.pdf",
            "name": "document.pdf",
            "size": 512000,
            "mtime": day_ago,
        },
        {
            "path": "/downloads/old/document.pdf",
            "name": "document.pdf",
            "size": 1000000,
            "mtime": week_ago,
        },
        {
            "path": "/var/logs/malware.log",
            "name": "malware.log",
            "size": 5000,
            "mtime": now,
        },
        {
            "path": "/cache/image.jpg",
            "name": "image.jpg",
            "size": 2048000,
            "mtime": day_ago,
        },
    ]


@pytest.fixture
def matcher():
    """Matcher instance for testing."""
    return FileMatcher()


class TestFileMatcher:
    """Test FileMatcher functionality."""

    def test_single_file_match(self, matcher, sample_batch_files):
        """Test matching single file without duplicates."""
        result = matcher.match_files(["malware.log"], sample_batch_files)

        assert len(result.files) == 1
        assert "/var/logs/malware.log" in result.files
        assert result.duplicates_resolved == 0

    def test_duplicate_resolution_by_freshness(self, matcher, sample_batch_files):
        """Test duplicate resolution prefers newer files."""
        result = matcher.match_files(
            ["document.pdf"],
            sample_batch_files,
            case_context="find documents"
        )

        assert len(result.files) == 1
        assert "/home/user/documents/document.pdf" in result.files
        assert result.duplicates_resolved == 1

    def test_duplicate_resolution_with_context(self, matcher, sample_batch_files):
        """Test semantic scoring with case context."""
        result = matcher.match_files(
            ["document.pdf"],
            sample_batch_files,
            case_context="find contract documents in user folder"
        )

        assert "/home/user/documents/document.pdf" in result.files

    def test_no_match_items(self, matcher, sample_batch_files):
        """Test items that don't match any files."""
        result = matcher.match_files(
            ["nonexistent.pdf", "also_missing.txt"],
            sample_batch_files
        )

        assert len(result.files) == 0
        assert len(result.no_matches) == 2

    def test_confidence_scores(self, matcher, sample_batch_files):
        """Test confidence scores are assigned."""
        result = matcher.match_files(
            ["malware.log", "document.pdf"],
            sample_batch_files
        )

        malware_score = result.confidence_scores.get("/var/logs/malware.log", 0)
        assert malware_score == 1.0

        doc_score = result.confidence_scores.get("/home/user/documents/document.pdf", 0)
        assert 0 <= doc_score <= 1.0

    def test_path_semantic_scoring(self, matcher):
        """Test path semantic scoring."""
        file = {"path": "/home/user/contract/document.pdf", "mtime": time.time()}

        # "contract document" - 2 out of 2 keywords match = 1.0
        score = matcher._score_path_semantic(file, "contract document")
        assert score > 0.5

        # "find malware infection" - 0 out of 3 keywords match = 0.0
        score = matcher._score_path_semantic(file, "find malware infection")
        assert score < 0.5

        # "user contract pdf document" - 4 out of 4 keywords match = 1.0
        score = matcher._score_path_semantic(file, "user contract pdf document")
        assert score > 0.9

    def test_freshness_scoring(self, matcher):
        """Test freshness scoring."""
        now = int(time.time())

        new_file = {"mtime": now}
        assert matcher._score_freshness(new_file) > 0.9

        old_file = {"mtime": now - 365 * 86400}
        assert matcher._score_freshness(old_file) < 0.5

    def test_size_scoring(self, matcher):
        """Test size scoring."""
        large = {"size": 20 * 1024 * 1024}
        assert matcher._score_size(large) > 0.9

        small = {"size": 500}
        assert matcher._score_size(small) < 0.5

    def test_depth_scoring(self, matcher):
        """Test path depth scoring."""
        shallow = {"path": "/file.txt"}
        assert matcher._score_depth(shallow) > 0.9

        deep = {"path": "/a/b/c/d/e/f/g/h/file.txt"}
        assert matcher._score_depth(deep) < 0.5

    def test_multiple_items_mixed_results(self, matcher, sample_batch_files):
        """Test matching multiple items with mixed results."""
        result = matcher.match_files(
            ["malware.log", "document.pdf", "missing.txt", "image.jpg"],
            sample_batch_files
        )

        assert len(result.files) == 3
        assert len(result.no_matches) == 1
        assert "missing.txt" in result.no_matches
