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
from .extractors import get_extractor

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
        
        # Special fallback for LevelDB directories
        if path.is_dir() and (path / "CURRENT").exists():
            ext = "leveldb"
        else:
            ext = path.suffix.lower()

        # Retrieve extractor from dynamic registry
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
