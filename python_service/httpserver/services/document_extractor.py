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
        }

    def get_extractor(self, file_path: str) -> Optional[BaseExtractor]:
        path = Path(file_path)
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
