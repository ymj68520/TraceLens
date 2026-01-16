"""
Unit tests for toon_transformer module.
"""

import json
from datetime import datetime, timezone

import pytest

from graphiti_integration.database_reader import FileRecord
from graphiti_integration.toon_transformer import TOONTransformer, EpisodeData
from graphiti_integration.exceptions import TransformationError


@pytest.fixture
def sample_record():
    """Create a sample FileRecord for testing."""
    return FileRecord(
        id=1,
        inode=12345,
        name="important_document.pdf",
        path="/data/documents/important_document.pdf",
        size=102400,
        extension="pdf",
        category="Documents",
        file_type="REG",
        mtime=1704067200,  # 2024-01-01 00:00:00 UTC
        ctime=1704067100,
        is_deleted=False,
        md5="abc123def456",
        llm_summary="A quarterly financial report for Q4 2023",
        llm_description="This document contains detailed financial analysis including revenue, expenses, and profit margins for the fourth quarter of 2023.",
        llm_keywords="financial,report,Q4,2023,quarterly",
        llm_analyzed_at=1704067300,
        llm_model_used="gpt-4",
    )


@pytest.fixture
def record_without_analysis():
    """Create a FileRecord without LLM analysis."""
    return FileRecord(
        id=2,
        inode=12346,
        name="unanalyzed.txt",
        path="/data/text/unanalyzed.txt",
        size=256,
        extension="txt",
        category="Unknown",
        file_type="REG",
        mtime=1704067200,
        ctime=1704067100,
        is_deleted=False,
        md5="xyz789",
    )


class TestTOONTransformer:
    """Tests for TOONTransformer class."""
    
    def test_transform_creates_episode_data(self, sample_record):
        """Test basic transformation creates EpisodeData."""
        transformer = TOONTransformer()
        episode = transformer.transform(sample_record)
        
        assert isinstance(episode, EpisodeData)
        assert episode.file_path == sample_record.path
        assert episode.file_id == sample_record.id
        assert episode.category == sample_record.category
    
    def test_transform_episode_name(self, sample_record):
        """Test episode name creation."""
        transformer = TOONTransformer()
        episode = transformer.transform(sample_record)
        
        assert episode.name == "Documents:important_document.pdf"
    
    def test_transform_episode_body_structure(self, sample_record):
        """Test episode body contains expected structure."""
        transformer = TOONTransformer()
        episode = transformer.transform(sample_record)
        
        body = json.loads(episode.episode_body)
        
        assert body["file_name"] == "important_document.pdf"
        assert body["file_path"] == "/data/documents/important_document.pdf"
        assert body["category"] == "Documents"
        assert "metadata" in body
        assert "analysis" in body
    
    def test_transform_includes_metadata(self, sample_record):
        """Test metadata is included in episode body."""
        transformer = TOONTransformer(include_metadata=True)
        episode = transformer.transform(sample_record)
        body = json.loads(episode.episode_body)
        
        assert body["metadata"]["size_bytes"] == 102400
        assert body["metadata"]["md5_hash"] == "abc123def456"
        assert body["metadata"]["is_deleted"] is False
    
    def test_transform_includes_analysis(self, sample_record):
        """Test LLM analysis is included in episode body."""
        transformer = TOONTransformer(include_analysis=True)
        episode = transformer.transform(sample_record)
        body = json.loads(episode.episode_body)
        
        assert body["analysis"]["summary"] == sample_record.llm_summary
        assert body["analysis"]["description"] == sample_record.llm_description
        assert body["analysis"]["keywords"] == ["financial", "report", "Q4", "2023", "quarterly"]
        assert body["analysis"]["model"] == "gpt-4"
    
    def test_transform_without_metadata(self, sample_record):
        """Test transformation with metadata disabled."""
        transformer = TOONTransformer(include_metadata=False)
        episode = transformer.transform(sample_record)
        body = json.loads(episode.episode_body)
        
        assert "metadata" not in body
        assert "analysis" in body  # Analysis still included
    
    def test_transform_without_analysis(self, sample_record):
        """Test transformation with analysis disabled."""
        transformer = TOONTransformer(include_analysis=False)
        episode = transformer.transform(sample_record)
        body = json.loads(episode.episode_body)
        
        assert "metadata" in body
        assert "analysis" not in body
    
    def test_transform_record_without_analysis(self, record_without_analysis):
        """Test transformation of record without LLM analysis."""
        transformer = TOONTransformer()
        episode = transformer.transform(record_without_analysis)
        body = json.loads(episode.episode_body)
        
        # Should not include analysis section
        assert "analysis" not in body
        # Should still include metadata
        assert "metadata" in body
    
    def test_transform_reference_time_from_analysis(self, sample_record):
        """Test reference time uses analysis timestamp."""
        transformer = TOONTransformer()
        episode = transformer.transform(sample_record)
        
        expected = datetime.fromtimestamp(sample_record.llm_analyzed_at, tz=timezone.utc)
        assert episode.reference_time == expected
    
    def test_transform_source_description(self):
        """Test custom source description."""
        transformer = TOONTransformer(source_description="custom_source")
        record = FileRecord(
            id=1, inode=1, name="test.txt", path="/test.txt",
            size=100, extension="txt", category="Unknown",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_analyzed_at=1704067300
        )
        episode = transformer.transform(record)
        
        assert episode.source_description == "custom_source"
    
    def test_transform_batch_success(self, sample_record, record_without_analysis):
        """Test batch transformation with multiple records."""
        transformer = TOONTransformer()
        records = [sample_record, record_without_analysis]
        
        episodes, errors = transformer.transform_batch(records)
        
        assert len(episodes) == 2
        assert len(errors) == 0
    
    def test_transform_batch_with_errors(self, sample_record):
        """Test batch transformation handles errors gracefully."""
        transformer = TOONTransformer()
        
        # Create a broken record that will fail transformation
        broken_record = FileRecord(
            id=999, inode=0, name=None, path=None,  # type: ignore - intentionally broken
            size=0, extension="", category="",
            file_type="", mtime=0, ctime=0, is_deleted=False, md5="",
        )
        
        records = [sample_record, broken_record]
        episodes, errors = transformer.transform_batch(records, skip_errors=True)
        
        # First record should succeed (or both if broken one doesn't actually fail)
        assert len(episodes) >= 1
    
    def test_episode_data_as_dict(self, sample_record):
        """Test EpisodeData.as_dict property."""
        transformer = TOONTransformer()
        episode = transformer.transform(sample_record)
        
        d = episode.as_dict
        assert "name" in d
        assert "episode_body" in d
        assert "source_description" in d
        assert "reference_time" in d
    
    def test_to_toon_format(self, sample_record, record_without_analysis):
        """Test TOON text format export."""
        transformer = TOONTransformer()
        records = [sample_record, record_without_analysis]
        
        toon_output = transformer.to_toon_format(records)
        
        assert "TOON.schema:" in toon_output
        assert "# records[2]" in toon_output
        assert "important_document.pdf" in toon_output


class TestEpisodeData:
    """Tests for EpisodeData dataclass."""
    
    def test_as_dict(self):
        """Test as_dict returns correct keys."""
        episode = EpisodeData(
            name="test_episode",
            episode_body='{"key": "value"}',
            source_description="test_source",
            reference_time=datetime.now(timezone.utc),
            file_path="/test/path",
            file_id=1,
        )
        
        d = episode.as_dict
        assert set(d.keys()) == {"name", "episode_body", "source_description", "reference_time"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
