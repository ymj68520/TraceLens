"""
Unit tests for FilterResultValidator.
"""

import pytest

from httpserver.services.case_analysis.filter_validator import (
    FilterResultValidator,
    ValidationResult,
)
from httpserver.services.case_analysis.llm_response_parser import (
    ParseResult,
)


@pytest.fixture
def sample_batch_files():
    """Sample batch files."""
    return [
        {"path": "/home/user/doc.pdf", "name": "doc.pdf"},
        {"path": "/tmp/image.jpg", "name": "image.jpg"},
    ]


@pytest.fixture
def validator():
    """Validator instance."""
    return FilterResultValidator()


class TestFilterResultValidator:
    """Test FilterResultValidator functionality."""

    def test_validate_valid_result(self, validator, sample_batch_files):
        """Test validating a valid result."""
        parse_result = ParseResult(
            selected_files=["/home/user/doc.pdf"],
            confidence=0.9
        )

        result = validator.validate_and_repair(parse_result, sample_batch_files, 10)

        assert result.is_valid
        assert len(result.items) == 1
        assert "/home/user/doc.pdf" in result.items

    def test_validate_empty_result(self, validator, sample_batch_files):
        """Test validating empty result."""
        parse_result = ParseResult(selected_files=[], confidence=0.0)

        result = validator.validate_and_repair(parse_result, sample_batch_files, 10)

        assert not result.is_valid
        assert len(result.items) == 0
        assert len(result.warnings) > 0

    def test_validate_low_confidence(self, validator, sample_batch_files):
        """Test low confidence is flagged."""
        parse_result = ParseResult(
            selected_files=["/home/user/doc.pdf"],
            confidence=0.1
        )

        result = validator.validate_and_repair(parse_result, sample_batch_files, 10)

        assert not result.is_valid
        assert any("confidence" in w.lower() for w in result.warnings)

    def test_validate_trim_excess(self, validator, sample_batch_files):
        """Test trimming excess files."""
        parse_result = ParseResult(
            selected_files=["/home/user/doc.pdf"] * 100,
            confidence=1.0
        )

        result = validator.validate_and_repair(parse_result, sample_batch_files, 5)

        assert len(result.items) <= 5
        assert any("trim" in r.lower() for r in result.repairs_made)

    def test_validate_remove_invalid(self, validator, sample_batch_files):
        """Test removing files not in batch."""
        parse_result = ParseResult(
            selected_files=[
                "/home/user/doc.pdf",
                "/nonexistent/file.txt",
            ],
            confidence=0.8
        )

        result = validator.validate_and_repair(parse_result, sample_batch_files, 10)

        assert len(result.items) == 1
        assert "/home/user/doc.pdf" in result.items
        assert "/nonexistent/file.txt" not in result.items

    def test_handle_invalid_response_regex_extract(self, validator, sample_batch_files):
        """Test handling invalid response with regex extraction."""
        response = "I found doc.pdf and image.jpg in the analysis"

        result = validator.handle_invalid_response(response, sample_batch_files)

        assert result.is_valid
        assert len(result.items) >= 1
        assert any("regex" in r.lower() for r in result.repairs_made)

    def test_handle_invalid_response_fallback(self, validator, sample_batch_files):
        """Test handling completely invalid response."""
        response = "No relevant files found in this analysis"

        result = validator.handle_invalid_response(response, sample_batch_files)

        assert not result.is_valid
        assert len(result.items) == 0

    def test_aggressive_regex_extract(self, validator):
        """Test aggressive regex extraction."""
        text = "The analysis found doc.pdf which is important"
        files = [
            {"path": "/home/user/doc.pdf", "name": "doc.pdf"},
            {"path": "/tmp/other.txt", "name": "other.txt"},
        ]

        result = validator._aggressive_regex_extract(text, files)

        assert "/home/user/doc.pdf" in result

    def test_fuzzy_match(self, validator):
        """Test fuzzy matching."""
        text = "Found some PDF documents"
        files = [
            {"path": "/home/user/doc.pdf", "name": "doc.pdf"},
            {"path": "/tmp/file.txt", "name": "file.txt"},
        ]

        result = validator._fuzzy_match(text, files)

        assert any("doc.pdf" in p for p in result)
