"""
Unit tests for database_reader module.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from graphiti_integration.database_reader import ForensicsDatabase, FileRecord
from graphiti_integration.exceptions import DatabaseError


@pytest.fixture
def sample_db():
    """Create a temporary database with sample data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            extension TEXT,
            category TEXT,
            type TEXT,
            mtime INTEGER,
            ctime INTEGER,
            is_deleted INTEGER,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT
        )
    """)
    
    # Insert test data
    test_files = [
        (1, "document1.pdf", "/data/docs/document1.pdf", 1024, "pdf", "Documents", "REG", 
         1704067200, 1704067200, 0, "abc123", 
         "Summary of document 1", "Detailed description", "keyword1,keyword2", 1704067300, "gpt-4"),
        (2, "image1.jpg", "/data/images/image1.jpg", 2048, "jpg", "Images", "REG",
         1704067400, 1704067400, 0, "def456",
         "Image summary", "Photo description", "photo,landscape", 1704067500, "gpt-4"),
        (3, "file_no_analysis.txt", "/data/text/file_no_analysis.txt", 512, "txt", "Unknown", "REG",
         1704067600, 1704067600, 0, "ghi789",
         None, None, None, None, None),
        (4, "deleted_file.doc", "/data/docs/deleted_file.doc", 768, "doc", "Documents", "REG",
         1704067700, 1704067700, 1, "jkl012",
         "Deleted doc summary", "Was a word doc", "deleted", 1704067800, "gpt-3.5"),
    ]
    
    conn.executemany("""
        INSERT INTO files (inode, name, path, size, extension, category, type, 
                          mtime, ctime, is_deleted, md5,
                          llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, test_files)
    
    conn.commit()
    conn.close()
    
    yield db_path
    
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


class TestFileRecord:
    """Tests for FileRecord dataclass."""
    
    def test_has_llm_analysis_true(self):
        """Test has_llm_analysis when analysis exists."""
        record = FileRecord(
            id=1, inode=1, name="test.pdf", path="/test.pdf",
            size=1024, extension="pdf", category="Documents",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_analyzed_at=1704067300
        )
        assert record.has_llm_analysis is True
    
    def test_has_llm_analysis_false(self):
        """Test has_llm_analysis when no analysis."""
        record = FileRecord(
            id=1, inode=1, name="test.pdf", path="/test.pdf",
            size=1024, extension="pdf", category="Documents",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_analyzed_at=None
        )
        assert record.has_llm_analysis is False
    
    def test_keywords_list_comma_separated(self):
        """Test parsing comma-separated keywords."""
        record = FileRecord(
            id=1, inode=1, name="test.pdf", path="/test.pdf",
            size=1024, extension="pdf", category="Documents",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_keywords="keyword1, keyword2, keyword3"
        )
        assert record.keywords_list == ["keyword1", "keyword2", "keyword3"]
    
    def test_keywords_list_json_array(self):
        """Test parsing JSON array keywords."""
        record = FileRecord(
            id=1, inode=1, name="test.pdf", path="/test.pdf",
            size=1024, extension="pdf", category="Documents",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_keywords='["keyword1", "keyword2"]'
        )
        assert record.keywords_list == ["keyword1", "keyword2"]
    
    def test_keywords_list_empty(self):
        """Test empty keywords."""
        record = FileRecord(
            id=1, inode=1, name="test.pdf", path="/test.pdf",
            size=1024, extension="pdf", category="Documents",
            file_type="REG", mtime=0, ctime=0, is_deleted=False, md5="abc",
            llm_keywords=None
        )
        assert record.keywords_list == []


class TestForensicsDatabase:
    """Tests for ForensicsDatabase class."""
    
    def test_init_missing_database(self):
        """Test error when database doesn't exist."""
        with pytest.raises(DatabaseError, match="Database not found"):
            ForensicsDatabase("/nonexistent/path.db")
    
    def test_count_files_all(self, sample_db):
        """Test counting all files."""
        db = ForensicsDatabase(sample_db)
        count = db.count_files()
        assert count == 4
    
    def test_count_files_analyzed_only(self, sample_db):
        """Test counting only analyzed files."""
        db = ForensicsDatabase(sample_db)
        count = db.count_files(analyzed_only=True)
        assert count == 3  # One file has no analysis
    
    def test_count_files_by_category(self, sample_db):
        """Test counting files by category."""
        db = ForensicsDatabase(sample_db)
        count = db.count_files(categories=["Documents"])
        assert count == 2
    
    def test_get_files_all(self, sample_db):
        """Test fetching all files."""
        db = ForensicsDatabase(sample_db)
        files = db.get_files()
        assert len(files) == 4
        assert all(isinstance(f, FileRecord) for f in files)
    
    def test_get_files_analyzed_only(self, sample_db):
        """Test fetching only analyzed files."""
        db = ForensicsDatabase(sample_db)
        files = db.get_files(analyzed_only=True)
        assert len(files) == 3
        assert all(f.has_llm_analysis for f in files)
    
    def test_get_files_with_limit_offset(self, sample_db):
        """Test pagination with limit and offset."""
        db = ForensicsDatabase(sample_db)
        
        # Get first 2 files
        first_batch = db.get_files(limit=2, offset=0)
        assert len(first_batch) == 2
        
        # Get next 2 files
        second_batch = db.get_files(limit=2, offset=2)
        assert len(second_batch) == 2
        
        # Files should be different
        first_paths = {f.path for f in first_batch}
        second_paths = {f.path for f in second_batch}
        assert first_paths.isdisjoint(second_paths)
    
    def test_iter_files_batched(self, sample_db):
        """Test batch iteration."""
        db = ForensicsDatabase(sample_db)
        
        batches = list(db.iter_files_batched(batch_size=2))
        
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
    
    def test_get_categories(self, sample_db):
        """Test getting unique categories."""
        db = ForensicsDatabase(sample_db)
        categories = db.get_categories()
        
        assert "Documents" in categories
        assert "Images" in categories
        assert "Unknown" in categories
    
    def test_get_analysis_stats(self, sample_db):
        """Test getting analysis statistics."""
        db = ForensicsDatabase(sample_db)
        stats = db.get_analysis_stats()
        
        assert stats["total_files"] == 4
        assert stats["analyzed_files"] == 3
        assert stats["total_size"] == 1024 + 2048 + 512 + 768
        assert stats["analysis_percentage"] == 75.0
    
    def test_file_record_data(self, sample_db):
        """Test that FileRecord data is correctly populated."""
        db = ForensicsDatabase(sample_db)
        files = db.get_files()
        
        # Find the document file
        doc = next(f for f in files if f.name == "document1.pdf")
        
        assert doc.path == "/data/docs/document1.pdf"
        assert doc.size == 1024
        assert doc.category == "Documents"
        assert doc.llm_summary == "Summary of document 1"
        assert doc.llm_model_used == "gpt-4"
        assert doc.has_llm_analysis is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
