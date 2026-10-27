from abc import ABC, abstractmethod
from typing import List, Tuple, Union
from dataclasses import dataclass, field
from typing import Any
import re


class DocumentContentUnavailableError(Exception):
    """The document's real content cannot be extracted for analysis.

    Raised instead of returning error text as document content: an error
    string that reaches the LLM reads like evidence and produces a confident
    but meaningless analysis. Causes include overwritten deleted-file
    clusters, unsupported/corrupt containers, and missing external tools.
    Messages are user-facing (they surface through the analyze routes).
    """

    def __init__(self, message="材料没有可供分析的正文", *, code="DOCUMENT_CONTENT_UNAVAILABLE", status="error"):
        super().__init__(message)
        self.code = code
        self.status = status


def validate_extracted_text(text: str) -> str:
    """Reject legacy extractor diagnostics, never inspect raw evidence bytes."""
    if re.match(r"^\s*(?:Error:|\[No content extracted from |An error occurred while reading the file)", text or "", re.I):
        raise DocumentContentUnavailableError("解析器未取得有效正文，诊断信息不得作为证据", code="PARSER_DIAGNOSTIC_NOT_EVIDENCE")
    return text


@dataclass(frozen=True)
class ExtractionResult:
    """Typed parser outcome; diagnostics are deliberately separate from content."""

    status: str
    parser: str
    parser_version: str = "1"
    text: str = ""
    records: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    diagnostics_separated: bool = False

    def require_content(self) -> str:
        if self.status not in {"ok", "partial"} or not self.text.strip():
            code = self.diagnostics[0] if self.diagnostics else "SOURCE_HAS_NO_READABLE_CONTENT"
            raise DocumentContentUnavailableError(
                "材料解析未取得有效正文，执行次数、时间等未知字段保持未知",
                code=code, status=self.status,
            )
        return self.text if self.diagnostics_separated else validate_extracted_text(self.text)


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
        result = await self.extract_result(file_path)
        return result.require_content(), type(self).__name__

    async def extract_result(self, file_path: str) -> ExtractionResult:
        text = validate_extracted_text(await self.extract_to_markdown(file_path))
        return ExtractionResult(status="ok" if text.strip() else "metadata_only",
                                parser=type(self).__name__, text=text)


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
