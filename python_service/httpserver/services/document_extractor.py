"""
Document Extractor Service (Facade).

This module now acts as a routing facade. The actual extraction logic has been 
refactored into isolated plugins within the `extractors/` package.
"""

import logging
import os
from pathlib import Path
from typing import Optional

# Import the base and the registry loader
from .extractors.base import BaseExtractor
from .extractors import get_extractor, get_extractor_by_filename

logger = logging.getLogger(__name__)

class ExtractorLocator:
    """
    Locator for finding the right extractor plugin based on file extension.
    It dynamically queries the `extractors` plugin registry.
    """
    def __init__(self):
        pass
        
    def get_extractor(self, file_path: str) -> Optional[BaseExtractor]:
        """Locates the appropriate extractor for the given file path."""
        path = Path(file_path)

        # Filename-based routing must come first: registry hives (SAM, SYSTEM,
        # SOFTWARE, SECURITY, DEFAULT, NTUSER.DAT) and Linux logs (wtmp, btmp)
        # have no extension, so the empty-extension branch below used to return
        # None before their names were ever consulted. The hives then fell
        # through to markitdown, which cannot read them, and every registry
        # artifact in a case failed with HTTP 500.
        extractor = get_extractor_by_filename(path.name)
        if extractor:
            logger.info(f"Routed '{path.name}' to {extractor.__class__.__name__} (by filename)")
            return extractor

        # Special fallback for LevelDB directories
        if path.is_dir() and (path / "CURRENT").exists():
            ext = "leveldb"
        elif not path.suffix:
            head = b""
            try:
                with open(file_path, "rb") as f:
                    head = f.read(8)
            except Exception:
                pass
            text_mime_candidates = {b"\xEF\xBB\xBF", b"#!", b"<?xml", b"<html", b"<!DOC", b"{\n", b"[{", b"# "}
            if head and any(head.startswith(candidate) for candidate in text_mime_candidates):
                ext = ".txt"
            else:
                logger.info("No extractor available for empty extension: %s", file_path)
                return None
        else:
            ext = path.suffix.lower()

        # Fall back to extension-based routing
        extractor = get_extractor(ext)
        if extractor:
            logger.info(f"Routed {ext} to {extractor.__class__.__name__}")
        else:
            logger.warning(f"No extractor available for {ext}")

        return extractor

# Singleton pattern for the locator
_document_extractor_locator: Optional[ExtractorLocator] = None

def get_document_extractor_locator() -> ExtractorLocator:
    global _document_extractor_locator
    if _document_extractor_locator is None:
        _document_extractor_locator = ExtractorLocator()
    return _document_extractor_locator
