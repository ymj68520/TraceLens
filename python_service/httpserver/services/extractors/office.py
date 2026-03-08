import logging
from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

@register_extractor
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

@register_extractor
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

@register_extractor
class OfficeServiceAdapter(BaseExtractor):
    """Adapter for existing office_service.py for Excel/PPT formats."""
    async def extract_to_markdown(self, file_path: str) -> str:
        # Since office_service.py is usually in the parent directory of extractors
        from ..office_service import get_office_service
        service = get_office_service()
        return await service.parse_file(file_path)

@register_extractor
class DocExtractorProxy(BaseExtractor):
    """Attempt to parse .doc using catdoc or fallback."""
    async def extract_to_markdown(self, file_path: str) -> str:
        import subprocess
        try:
            # Let's use antiword to parse .doc locally
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
