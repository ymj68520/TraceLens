"""
Unit tests for LLMResponseParser.
"""

import pytest

from httpserver.services.case_analysis.llm_response_parser import (
    LLMResponseParser,
    ParseResult,
)


@pytest.fixture
def sample_batch_files():
    """Sample batch files for testing."""
    return [
        {"path": "/home/user/document.pdf", "name": "document.pdf", "size": 1024},
        {"path": "/tmp/image.jpg", "name": "image.jpg", "size": 2048},
        {"path": "/var/logs/app.log", "name": "app.log", "size": 512},
        {"path": "/downloads/malware.exe", "name": "malware.exe", "size": 4096},
    ]


@pytest.fixture
def parser():
    """Parser instance for testing."""
    return LLMResponseParser()


class TestLLMResponseParser:
    """Test LLMResponseParser functionality."""

    def test_parse_clean_json_dict(self, parser, sample_batch_files):
        """Test parsing clean JSON dict format."""
        response = '{"selected_files": ["document.pdf", "malware.exe"], "reasoning": "Found relevant files"}'

        result = parser.parse_filter_response(response, sample_batch_files)

        assert len(result.selected_files) == 2
        assert "/home/user/document.pdf" in result.selected_files
        assert "/downloads/malware.exe" in result.selected_files
        assert result.reasoning == "Found relevant files"
        assert result.confidence == 1.0

    def test_parse_json_array(self, parser, sample_batch_files):
        """Test parsing JSON array format."""
        response = '["document.pdf", "image.jpg"]'

        result = parser.parse_filter_response(response, sample_batch_files)

        assert len(result.selected_files) == 2
        assert "/home/user/document.pdf" in result.selected_files
        assert "/tmp/image.jpg" in result.selected_files

    def test_parse_markdown_wrapped(self, parser, sample_batch_files):
        """Test parsing JSON wrapped in markdown."""
        response = '''```json
        {"selected_files": ["app.log"], "reasoning": "Log file found"}
        ```'''

        result = parser.parse_filter_response(response, sample_batch_files)

        assert len(result.selected_files) == 1
        assert "/var/logs/app.log" in result.selected_files

    def test_parse_different_field_names(self, parser, sample_batch_files):
        """Test parsing with alternative field names."""
        # filtered_files
        response1 = '{"filtered_files": ["malware.exe"]}'
        result1 = parser.parse_filter_response(response1, sample_batch_files)
        assert len(result1.selected_files) == 1

        # files
        response2 = '{"files": ["document.pdf"]}'
        result2 = parser.parse_filter_response(response2, sample_batch_files)
        assert len(result2.selected_files) == 1

    def test_parse_with_explanation_text(self, parser, sample_batch_files):
        """Test parsing JSON embedded in explanatory text."""
        response = '''Based on the case description, I found these relevant files:

{"selected_files": ["document.pdf"], "reasoning": "Case-related document"}

The analysis is complete.'''

        result = parser.parse_filter_response(response, sample_batch_files)

        assert len(result.selected_files) == 1
        assert "/home/user/document.pdf" in result.selected_files

    def test_parse_invalid_json_fallback(self, parser, sample_batch_files):
        """Test fallback when JSON is invalid."""
        response = '''The relevant files are:
- document.pdf
- malware.exe
End of analysis'''

        result = parser.parse_filter_response(response, sample_batch_files)

        # Fallback should extract via regex
        assert len(result.selected_files) >= 1
        assert result.confidence < 1.0
        assert any("fallback" in a.lower() for a in result.repair_actions)

    def test_parse_empty_response(self, parser, sample_batch_files):
        """Test parsing completely empty/invalid response."""
        result = parser.parse_filter_response("No relevant files found", sample_batch_files)

        assert len(result.selected_files) == 0
        assert result.confidence == 0.0

    def test_validate_nonexistent_files(self, parser, sample_batch_files):
        """Test that non-existent files are filtered out."""
        response = '{"selected_files": ["document.pdf", "nonexistent.txt"]}'

        result = parser.parse_filter_response(response, sample_batch_files)

        # Only document.pdf should be validated
        assert len(result.selected_files) == 1
        assert "/home/user/document.pdf" in result.selected_files

    def test_extract_json_blocks_finds_multiple(self, parser):
        """Test JSON block extraction finds multiple blocks."""
        text = '''```json
        {"files": ["a"]}
        ```
        Some text
        ```json
        {"files": ["b"]}
        ```'''

        blocks = parser._extract_json_blocks(text)
        assert len(blocks) == 2

    def test_confidence_calculation(self, parser, sample_batch_files):
        """Test confidence score calculation."""
        # All valid
        response1 = '{"selected_files": ["document.pdf", "malware.exe"]}'
        result1 = parser.parse_filter_response(response1, sample_batch_files)
        assert result1.confidence == 1.0

        # Partially valid
        response2 = '{"selected_files": ["document.pdf", "nonexistent.txt"]}'
        result2 = parser.parse_filter_response(response2, sample_batch_files)
        assert result2.confidence == 0.5
