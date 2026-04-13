"""
Integration tests for enhanced file filtering.
"""

import pytest


class TestFileFilterIntegration:
    """Test integrated filtering pipeline."""

    def test_full_pipeline_clean_response(self):
        """Test full pipeline with clean LLM response."""
        from python_service.httpserver.services.case_analysis.llm_response_parser import LLMResponseParser
        from python_service.httpserver.services.case_analysis.file_matcher import FileMatcher
        from python_service.httpserver.services.case_analysis.filter_validator import FilterResultValidator

        batch_files = [
            {"name": "document.pdf", "path": "/home/user/document.pdf", "size": 1024000},
            {"name": "image.jpg", "path": "/tmp/image.jpg", "size": 204800},
        ]

        response = '{"selected_files": ["document.pdf"], "reasoning": "Found relevant doc"}'

        parser = LLMResponseParser()
        matcher = FileMatcher()
        validator = FilterResultValidator()

        # Parse
        parse_result = parser.parse_filter_response(response, batch_files)

        # Validate
        validated = validator.validate_and_repair(parse_result, batch_files, 10)

        # Match
        matched = matcher.match_files(validated.items, batch_files)

        assert len(matched.files) == 1
        assert "/home/user/document.pdf" in matched.files

    def test_pipeline_with_duplicates(self):
        """Test pipeline handles duplicate filenames."""
        from python_service.httpserver.services.case_analysis.file_matcher import FileMatcher

        batch_files = [
            {"name": "doc.pdf", "path": "/new/doc.pdf", "size": 1000, "mtime": 1000000},
            {"name": "doc.pdf", "path": "/old/doc.pdf", "size": 500, "mtime": 500000},
        ]

        matcher = FileMatcher()
        result = matcher.match_files(["doc.pdf"], batch_files)

        assert len(result.files) == 1
        assert result.duplicates_resolved == 1
