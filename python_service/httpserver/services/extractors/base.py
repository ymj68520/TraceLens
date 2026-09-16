from abc import ABC, abstractmethod
from typing import List, Tuple, Union

class BaseExtractor(ABC):
    """
    Abstract base class for all offline document extractors.
    Transforms complex file formats into pure text/markdown ready for LLM processing.
    """
    @abstractmethod
    async def extract_to_markdown(self, file_path: str) -> str:
        """
        Extract the text and format it.
        Args:
            file_path: Valid absolute path to the file to process.
        Returns:
            A string (Markdown preferably).
        """
        pass

    async def extract_to_markdown_detailed(self, file_path: str) -> Tuple[str, str]:
        """
        Extract and report which extractor produced the content (SPEC
        file-analysis D17 provenance chain).

        Args:
            file_path: Valid absolute path to the file to process.
        Returns:
            ``(markdown, extraction_method)`` — the default method is this
            extractor's class name: it was routed to directly, without any
            markitdown involvement.
        """
        return await self.extract_to_markdown(file_path), type(self).__name__


def register_extractor(cls):
    """
    Class decorator to identify an extractor plugin. 
    The file extension routing map is externally managed via extractor_mapping.json.
    """
    from . import registered_extractor_classes
    
    # We simply register the class type itself by its string name,
    # the manager will handle instantiation and mapping.
    registered_extractor_classes[cls.__name__] = cls
    return cls
