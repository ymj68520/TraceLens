from abc import ABC, abstractmethod
from typing import List, Union

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
