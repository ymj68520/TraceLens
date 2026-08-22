"""
MarkitdownExtractor - Primary file-to-markdown converter using Microsoft's markitdown library.

Supports: PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, HTML, CSV, JSON, XML,
          EPUB, IPYNB, RSS, images (EXIF+OCR), audio (transcription), and more.

Falls back to legacy extractors (PDFExtractor, DocxExtractor, etc.) when
markitdown conversion fails. Fallback wiring is configured in extractor_mapping.json.
"""

import asyncio
import logging
from pathlib import Path
from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


@register_extractor
class MarkitdownExtractor(BaseExtractor):
    """
    Primary extractor using Microsoft's markitdown library.

    Handles all markitdown-supported formats with automatic fallback:
    - If markitdown fails, delegates to the legacy extractor configured
      in extractor_mapping.json's "fallback" field.
    - Fallback extractors are wired at registry load time via _fallback_map.

    The MarkItDown instance is created once and reused (thread-safe).
    """

    def __init__(self):
        self._fallback_map = {}  # Populated by the registry loader
        try:
            from markitdown import MarkItDown
            self._md = MarkItDown()
            logger.info("MarkitdownExtractor initialized with MarkItDown engine")
        except ImportError as e:
            logger.error(f"markitdown library not installed: {e}")
            self._md = None
        except Exception as e:
            # MarkItDown() can also raise RuntimeError, OSError, or other
            # exceptions when the bundled magika ONNX model fails to load,
            # when onnxruntime is misconfigured, etc.  Catching only
            # ImportError lets these propagate to load_plugins(), which
            # silently skips MarkitdownExtractor — causing ALL document
            # extensions to fall through to legacy extractors (PDFExtractor,
            # DocxExtractor, ...) without any markitdown conversion.
            logger.error(f"MarkItDown engine failed to initialize: {e}", exc_info=True)
            self._md = None

    def _get_fallback(self, file_path: str) -> 'BaseExtractor | None':
        """Get the fallback extractor for the given file's extension."""
        ext = Path(file_path).suffix.lower()
        return self._fallback_map.get(ext)

    async def extract_to_markdown(self, file_path: str) -> str:
        """
        Convert a file to markdown using markitdown.

        If markitdown is unavailable or fails, falls back to the legacy
        extractor configured in _fallback_map (e.g., PDFExtractor for .pdf).

        Args:
            file_path: Absolute path to the file to convert.

        Returns:
            Markdown string representation of the file content.

        Raises:
            RuntimeError: If markitdown is not installed and no fallback is available.
            Exception: If both markitdown and fallback fail.
        """
        # If markitdown is not installed, try fallback directly
        if self._md is None:
            fallback = self._get_fallback(file_path)
            if fallback:
                logger.warning(f"markitdown not installed, falling back to {fallback.__class__.__name__} for {file_path}")
                return await fallback.extract_to_markdown(file_path)
            raise RuntimeError(
                "markitdown library is not installed and no fallback available. "
                "Install with: pip install 'markitdown[all]'"
            )

        try:
            # markitdown's convert() is synchronous, run in executor
            # to keep the async contract of extract_to_markdown()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._md.convert, file_path
            )

            markdown = result.markdown if result else ""
            title = getattr(result, 'title', None)

            # markitdown wraps read failures into the markdown body instead of
            # raising ("An error occurred while reading the file..."). Treating
            # that text as content would send an error message to the LLM as if
            # it were evidence, so surface it as a missing-file failure instead.
            if markdown and "an error occurred while reading the file" in markdown[:300].lower():
                logger.error(f"markitdown could not read {file_path}; refusing error text as content")
                raise FileNotFoundError(file_path)

            if title:
                logger.debug(f"markitdown extracted title: {title}")

            if not markdown or not markdown.strip():
                logger.warning(f"markitdown produced empty output for {file_path}")
                # Try fallback before giving up
                fallback = self._get_fallback(file_path)
                if fallback:
                    logger.info(f"Falling back to {fallback.__class__.__name__} for {file_path}")
                    return await fallback.extract_to_markdown(file_path)
                return f"[No content extracted from {file_path}]"

            logger.info(
                f"markitdown converted {file_path}: "
                f"{len(markdown)} chars"
            )
            return markdown

        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"markitdown conversion failed for {file_path}: {e}")
            # Try fallback before re-raising
            fallback = self._get_fallback(file_path)
            if fallback:
                logger.warning(f"Falling back to {fallback.__class__.__name__} for {file_path}: {e}")
                try:
                    return await fallback.extract_to_markdown(file_path)
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed for {file_path}: {fallback_error}")
                    raise fallback_error
            raise
