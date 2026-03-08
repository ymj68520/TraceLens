"""
Document Extractor Service.

Provides parsing capabilities for various documents:
- PDF
- DOCX
- XLSX/XLS (via office_service)
- PPTX/PPT (via office_service)

Returns content as Markdown for forensic LLM analysis.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class BaseExtractor(ABC):
    """Abstract base class for document extractors."""

    @abstractmethod
    async def extract_to_markdown(self, file_path: str) -> str:
        """Extract content from file and return as Markdown."""
        pass

class PDFExtractor(BaseExtractor):
    async def extract_to_markdown(self, file_path: str) -> str:
        import fitz  # PyMuPDF
        
        try:
            doc = fitz.open(file_path)
            result = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    result.append(f"## Page {page_num + 1}\n\n{text}\n")
                    
            doc.close()
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {e}")
            raise

class DocxExtractor(BaseExtractor):
    async def extract_to_markdown(self, file_path: str) -> str:
        import docx
        
        try:
            doc = docx.Document(file_path)
            result = []
            
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    result.append(f"{text}\n")
                    
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing DOCX {file_path}: {e}")
            raise

class OfficeServiceAdapter(BaseExtractor):
    """Adapter for existing office_service.py for Excel/PPT formats."""
    async def extract_to_markdown(self, file_path: str) -> str:
        from .office_service import get_office_service
        service = get_office_service()
        return await service.parse_file(file_path)

class DocExtractorProxy(BaseExtractor):
    """Attempt to parse .doc using catdoc or fallback."""
    async def extract_to_markdown(self, file_path: str) -> str:
        import subprocess
        try:
            # Let's use antiword to parse .doc locally, since we have it configured similarly
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.warning(f"antiword error: {result.stderr}")
                return f"Error parsing DOC: {result.stderr}"

            return result.stdout.strip()

        except FileNotFoundError:
            logger.error("antiword not found.")
            return "Error: antiword not found. Cannot parse .doc file."
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout parsing DOC {file_path}")
            return "Error: Timeout parsing DOC file."
        except Exception as e:
            logger.error(f"Error parsing DOC {file_path}: {e}")
            return f"Error parsing DOC file: {e}"

class SQLiteExtractor(BaseExtractor):
    """
    Extracts schema (CREATE TABLE statements) and a sample of rows from SQLite databases
    to present them as Markdown for AI analysis.
    """
    def __init__(self, sample_size: int = 50):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        import sqlite3
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            # Connect in read-only mode to prevent lock issues and accidental changes
            uri_path = f"file:{file_path}?mode=ro"
            conn = sqlite3.connect(uri_path, uri=True)
            cursor = conn.cursor()
            
            result = ["# SQLite Database Summary\n"]
            
            # 1. Extract Schema
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            
            if not tables:
                result.append("No tables found or empty database.\n")
                conn.close()
                return "\n".join(result)
                
            result.append(f"**Total Tables:** {len(tables)}\n")
            
            for table_name, schema_sql in tables:
                result.append(f"## Table: `{table_name}`")
                
                # Add schema
                result.append("### Schema:")
                result.append("```sql")
                result.append(schema_sql if schema_sql else "N/A")
                result.append("```\n")
                
                # 2. Extract Data Sample
                try:
                    cursor.execute(f"SELECT * FROM \"{table_name}\" LIMIT {self.sample_size}")
                    rows = cursor.fetchall()
                    
                    if not rows:
                        result.append("*No data in this table.*\n")
                        continue
                        
                    # Get column names
                    col_names = [description[0] for description in cursor.description]
                    
                    # Markdown Table Header
                    result.append("### Sample Data:")
                    header_line = "| " + " | ".join(col_names) + " |"
                    separator_line = "| " + " | ".join(["---"] * len(col_names)) + " |"
                    result.append(header_line)
                    result.append(separator_line)
                    
                    # Markdown Table Rows
                    for row in rows:
                        # Convert None to NULL, stringify the rest, limit length to prevent massive markdown
                        safe_row = []
                        for cell in row:
                            if cell is None:
                                safe_row.append("NULL")
                            elif isinstance(cell, bytes):
                                safe_row.append("[BLOB]")
                            else:
                                cell_str = str(cell).replace("|", "\\|").replace("\n", " ") # Escape pipe and newline
                                if len(cell_str) > 100:
                                    cell_str = cell_str[:97] + "..."
                                safe_row.append(cell_str)
                        row_line = "| " + " | ".join(safe_row) + " |"
                        result.append(row_line)
                    
                    if len(rows) == self.sample_size:
                        result.append(f"\n*(Showing only the first {self.sample_size} rows)*\n")
                    else:
                        result.append("\n")
                        
                except Exception as e:
                    logger.warning(f"Failed to extract rows from {table_name}: {e}")
                    result.append(f"*Failed to extract data: {e}*\n")
                    
            conn.close()
            return "\n".join(result)
            
        except sqlite3.Error as e:
            logger.error(f"SQLite error processing {file_path}: {e}")
            return f"Error: Failed to process SQLite database: {e}"
        except Exception as e:
            logger.error(f"Error parsing SQLite DB {file_path}: {e}")
            raise


class SqlDumpExtractor(BaseExtractor):
    """
    Extracts the beginning of a SQL dump file. Since SQL dumps can be massive
    (e.g., gigabytes), we only extract the first N lines. This usually includes
    the table schema (CREATE TABLE) and the initial INSERT statements, which
    is enough for the LLM to understand the structure and sample data.
    """
    def __init__(self, max_lines: int = 500):
        self.max_lines = max_lines
        
    async def extract_to_markdown(self, file_path: str) -> str:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            result = [f"# SQL Dump Summary (`{file_path.split('/')[-1]}`)\n"]
            result.append("```sql")
            
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for idx, line in enumerate(f):
                    if idx >= self.max_lines:
                        break
                    result.append(line.rstrip())
                    
            result.append("```\n")
            result.append(f"\n*(Truncated to first {self.max_lines} lines)*")
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error parsing SQL Dump {file_path}: {e}")
            return f"Error: Failed to read SQL Dump file: {e}"

class LevelDBExtractor(BaseExtractor):
    """
    Extracts key-value pairs from a LevelDB directory.
    To prevent large context consumption, it only samples the first 100 pairs.
    """
    def __init__(self, sample_size: int = 100):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        try:
            import plyvel
        except ImportError:
            return "Error: plyvel library is not installed. Please install plyvel to analyze LevelDB databases."
            
        try:
            # Connect in read-only mode to prevent lock issues
            db = plyvel.DB(file_path, create_if_missing=False)
            
            result = [f"# LevelDB Summary\n"]
            result.append("### Sample Data:")
            result.append("| Key | Value |")
            result.append("| --- | --- |")
            
            count = 0
            for key, value in db:
                if count >= self.sample_size:
                    break
                    
                # Safe decode
                try:
                    k_str = key.decode('utf-8', errors='replace')
                except:
                    k_str = str(key)
                    
                try:
                    v_str = value.decode('utf-8', errors='replace')
                    # Try format as JSON string if possible
                    try:
                        v_json = json.loads(v_str)
                        v_str = json.dumps(v_json)[:200]
                    except:
                        pass
                except:
                    v_str = "[Binary Data]"
                    
                # Escape markdown table characters
                k_str = k_str.replace("|", "\\|").replace("\n", " ").replace("\r", "")
                v_str = v_str.replace("|", "\\|").replace("\n", " ").replace("\r", "")
                
                if len(k_str) > 100: k_str = k_str[:97] + "..."
                if len(v_str) > 200: v_str = v_str[:197] + "..."
                
                result.append(f"| `{k_str}` | {v_str} |")
                count += 1
                
            db.close()
            
            if count == self.sample_size:
                result.append(f"\n*(Showing first {self.sample_size} keys)*")
            elif count == 0:
                result.append("\n*(Database is empty)*")
                
            return "\n".join(result)
            
        except plyvel.Error as e:
            logger.error(f"LevelDB error processing {file_path}: {e}")
            return f"Error: Failed to open LevelDB directory. Ensure the path is a valid LevelDB directory and is not locked: {e}"
        except Exception as e:
            logger.error(f"Error parsing LevelDB {file_path}: {e}")
            raise


class ExtractorLocator:
    """Locator/Factory for document extractors based on extensions."""
    
    def __init__(self):
        self._extractors = {
            ".pdf": PDFExtractor(),
            ".docx": DocxExtractor(),
            ".doc": DocExtractorProxy(),  # Using antiword
            ".xlsx": OfficeServiceAdapter(),
            ".xls": OfficeServiceAdapter(),
            ".pptx": OfficeServiceAdapter(),
            ".ppt": OfficeServiceAdapter(),
            ".db": SQLiteExtractor(),
            ".sqlite": SQLiteExtractor(),
            ".sqlite3": SQLiteExtractor(),
            ".sql": SqlDumpExtractor(),
            "leveldb": LevelDBExtractor(), # Special pseudo-extension for directories
        }

    def get_extractor(self, file_path: str) -> Optional[BaseExtractor]:
        from pathlib import Path
        path = Path(file_path)
        
        if path.is_dir():
            # Check for LevelDB characteristics
            if (path / 'CURRENT').exists() and (path / 'LOG').exists():
                return self._extractors.get("leveldb")
            return None
            
        suffix = path.suffix.lower()
        return self._extractors.get(suffix)

    def is_supported(self, file_path: str) -> bool:
        return self.get_extractor(file_path) is not None

# Global locator instance
_document_extractor_locator: Optional[ExtractorLocator] = None

def get_document_extractor_locator() -> ExtractorLocator:
    """Get the global ExtractorLocator instance."""
    global _document_extractor_locator
    if _document_extractor_locator is None:
        _document_extractor_locator = ExtractorLocator()
    return _document_extractor_locator
